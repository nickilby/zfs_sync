"""FastAPI application construction.

The application is built by :func:`create_app` rather than assembled at import
time. The previous module-level construction had two consequences worth naming:

* Startup branched on ``PYTEST_CURRENT_TEST`` and returned early, so
  configuration validation, ``init_db()`` and the scheduler were never
  exercised by any test. Those are precisely the paths where the scheduler
  no-op, the blocked event loop and the wrong-directory log check lived.
* Settings were read once, at import, so a test could not construct an app with
  different settings without reloading the module.

``app`` is still exported for ``uvicorn zfs_sync.api.app:app``.
"""

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.utils import get_openapi
from fastapi.responses import RedirectResponse, Response
from fastapi.staticfiles import StaticFiles

from zfs_sync.api.errors import register_exception_handlers
from zfs_sync.api.middleware.auth import get_current_system
from zfs_sync.config import get_settings
from zfs_sync.logging_config import get_logger, setup_logging

logger = get_logger(__name__)

#: Dashboard assets ship inside the package, not at the repository root. The
#: previous code resolved the directory two levels up from this file, landing
#: on a repo-root `static/` that it then created empty -- so it always skipped
#: the mount, and every asset the dashboard page references returned 404.
PACKAGE_STATIC_DIR = Path(__file__).resolve().parent.parent / "static"


async def _run_startup(app: FastAPI) -> None:
    """Validate configuration, prepare the database, start the scheduler."""
    settings = app.state.settings

    logger.info("Starting %s v%s", settings.app_name, settings.app_version)
    logger.info("Debug mode: %s", settings.debug)
    logger.info("Database: %s", settings.database_url)

    from zfs_sync.config.validation import ConfigurationError, validate_configuration

    try:
        validate_configuration(settings)
        logger.info("Configuration validation passed")
    except ConfigurationError as exc:
        logger.error("Configuration validation failed: %s", exc)
        raise

    from zfs_sync.database import init_db

    # Pass the app's settings through. Reading the global here would ignore an
    # injected configuration entirely -- the database would be created wherever
    # the process-wide default points, which on Linux is /var/lib/zfs-sync.
    init_db(settings)

    if not settings.auto_sync_enabled:
        logger.info("Automatic sync is disabled")
        return

    try:
        from zfs_sync.services.sync_scheduler import SyncSchedulerService

        scheduler = SyncSchedulerService()
        await scheduler.start_scheduler()
        app.state.sync_scheduler = scheduler
        logger.info("Sync scheduler started")
    except (RuntimeError, ValueError, OSError) as exc:
        logger.error("Failed to start sync scheduler: %s", exc, exc_info=True)


async def _run_shutdown(app: FastAPI) -> None:
    """Stop the scheduler if it was started."""
    logger.info("Shutting down %s", app.state.settings.app_name)

    scheduler = getattr(app.state, "sync_scheduler", None)
    if scheduler is None:
        return

    try:
        await scheduler.stop_scheduler()
        logger.info("Sync scheduler stopped")
    except (RuntimeError, ValueError, OSError) as exc:
        logger.error("Error stopping sync scheduler: %s", exc, exc_info=True)


def _mount_static(app: FastAPI) -> None:
    """Serve the dashboard's CSS and JavaScript.

    The dashboard page references `/static/dashboard/...`, so this mount is
    what makes the page work rather than render unstyled and inert.
    """
    if not PACKAGE_STATIC_DIR.is_dir():
        logger.warning(
            "Static directory %s not found; dashboard assets will 404", PACKAGE_STATIC_DIR
        )
        return

    app.mount("/static", StaticFiles(directory=str(PACKAGE_STATIC_DIR)), name="static")
    logger.debug("Mounted static files from %s", PACKAGE_STATIC_DIR)

    assets_dir = PACKAGE_STATIC_DIR / "assets"
    if assets_dir.is_dir():
        app.mount("/assets", StaticFiles(directory=str(assets_dir)), name="assets")


def _customise_openapi(app: FastAPI) -> None:
    """Advertise the API key scheme in the generated schema."""

    def openapi():
        if app.openapi_schema:
            return app.openapi_schema

        schema = get_openapi(
            title=app.title,
            version=app.version,
            description=app.description,
            routes=app.routes,
        )
        components = schema.setdefault("components", {})
        components.setdefault("securitySchemes", {})["ApiKeyAuth"] = {
            "type": "apiKey",
            "in": "header",
            "name": "X-API-Key",
            "description": "System API key, issued once at registration.",
        }
        app.openapi_schema = schema
        return schema

    app.openapi = openapi


def create_app(settings=None, configure_logging: bool = True) -> FastAPI:
    """Build the application.

    Args:
        settings: Settings to run with. Defaults to the process-wide settings.
            Injectable so a test can exercise startup without reaching for
            environment variables or reloading this module.
        configure_logging: Whether to install logging handlers. Off in tests,
            where pytest manages capture.
    """
    settings = settings if settings is not None else get_settings()

    if configure_logging:
        setup_logging(log_file=settings.log_file)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        await _run_startup(app)
        try:
            yield
        finally:
            await _run_shutdown(app)

    app = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        description="A witness service to keep ZFS snapshots in sync across platforms",
        docs_url="/docs",
        redoc_url="/redoc",
        lifespan=lifespan,
    )
    app.state.settings = settings

    register_exception_handlers(app)

    app.add_middleware(
        CORSMiddleware,
        # allow_origins=["*"] with allow_credentials=True is rejected by
        # browsers and is the wrong default for a service that returns
        # infrastructure topology. Credentials are only allowed when specific
        # origins are named.
        allow_origins=settings.cors_allow_origins,
        allow_credentials="*" not in settings.cors_allow_origins,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    from zfs_sync.api.routes import (
        conflicts,
        dashboard,
        health,
        snapshots,
        sync,
        sync_groups,
        systems,
    )

    # Authentication is declared per router, so a new endpoint is protected by
    # default rather than by memory. Only 6 of 54 endpoints were protected
    # before, including none of the destructive ones.
    #
    # `health` is exempt so probes work without credentials, and `systems` is
    # exempt at the router level because registration must stay reachable; its
    # other routes carry the dependency individually.
    authenticated = [Depends(get_current_system)]
    routers = [
        (health.router, "Health", []),
        (systems.router, "Systems", []),
        (snapshots.router, "Snapshots", authenticated),
        (sync_groups.router, "Sync Groups", authenticated),
        (sync.router, "Sync", authenticated),
        (conflicts.router, "Conflicts", authenticated),
    ]
    for router, tag, dependencies in routers:
        app.include_router(
            router, prefix=settings.api_prefix, tags=[tag], dependencies=dependencies
        )

    app.include_router(dashboard.router, tags=["Dashboard"])

    @app.get("/", include_in_schema=False)
    async def root():
        return RedirectResponse(url="/dashboard")

    @app.get("/favicon.ico", include_in_schema=False)
    async def favicon():
        return Response(status_code=204)

    _mount_static(app)
    _customise_openapi(app)

    return app


#: The application uvicorn serves: `uvicorn zfs_sync.api.app:app`.
app = create_app()
