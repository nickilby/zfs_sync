"""FastAPI application setup."""

import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

from zfs_sync.config import get_settings
from zfs_sync.logging_config import get_logger, setup_logging

# Get settings first to access log_file
settings = get_settings()

# Setup logging with log file if configured
setup_logging(log_file=settings.log_file)
logger = get_logger(__name__)

# Settings already loaded above for logging setup

def _running_under_pytest() -> bool:
    """Return True when running under pytest."""
    return bool(os.environ.get("PYTEST_CURRENT_TEST"))


async def _run_startup(app_instance: FastAPI) -> None:
    """Initialize application resources."""
    logger.info("Starting %s v%s", settings.app_name, settings.app_version)
    logger.info("Debug mode: %s", settings.debug)
    logger.info("Database: %s", settings.database_url)

    # Skip validation and database initialization if we're in a test environment
    # (tests handle their own database setup via fixtures)
    if _running_under_pytest():
        logger.info(
            "Skipping configuration validation and database initialization in test environment"
        )
        return

    # Validate configuration before proceeding
    try:
        from zfs_sync.config.validation import ConfigurationError, validate_configuration

        validate_configuration(settings)
        logger.info("Configuration validation passed")
    except ConfigurationError as exc:
        logger.error("Configuration validation failed: %s", exc)
        raise

    # Initialize database
    from zfs_sync.database import init_db

    init_db()
    logger.info("Database initialized")

    # Start sync scheduler if enabled
    if settings.auto_sync_enabled:
        try:
            from zfs_sync.services.sync_scheduler import SyncSchedulerService

            scheduler = SyncSchedulerService()
            await scheduler.start_scheduler()
            # Store scheduler instance in app state for shutdown
            app_instance.state.sync_scheduler = scheduler
            logger.info("Sync scheduler started")
        except (RuntimeError, ValueError, OSError) as exc:
            logger.error("Failed to start sync scheduler: %s", exc, exc_info=True)
    else:
        logger.info("Automatic sync is disabled")


async def _run_shutdown(app_instance: FastAPI) -> None:
    """Cleanup application resources."""
    logger.info("Shutting down %s", settings.app_name)

    # Stop sync scheduler if it was started
    if hasattr(app_instance.state, "sync_scheduler"):
        try:
            scheduler = app_instance.state.sync_scheduler
            await scheduler.stop_scheduler()
            logger.info("Sync scheduler stopped")
        except (RuntimeError, ValueError, OSError) as exc:
            logger.error("Error stopping sync scheduler: %s", exc, exc_info=True)


@asynccontextmanager
async def lifespan(app_instance: FastAPI):
    """Manage FastAPI startup/shutdown lifecycle."""
    await _run_startup(app_instance)
    try:
        yield
    finally:
        await _run_shutdown(app_instance)


# Create FastAPI app
app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    description="A witness service to keep ZFS snapshots in sync across different platforms",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)


def custom_openapi():
    """Customize OpenAPI schema to include API key security scheme."""
    from fastapi.openapi.utils import get_openapi

    if app.openapi_schema:
        return app.openapi_schema

    openapi_schema = get_openapi(
        title=settings.app_name,
        version=settings.app_version,
        description="A witness service to keep ZFS snapshots in sync across different platforms",
        routes=app.routes,
    )

    # Ensure components section exists
    if "components" not in openapi_schema:
        openapi_schema["components"] = {}

    # Add or update API key security scheme
    if "securitySchemes" not in openapi_schema["components"]:
        openapi_schema["components"]["securitySchemes"] = {}

    # Add API key security scheme (will merge with any auto-generated schemes)
    openapi_schema["components"]["securitySchemes"]["ApiKeyAuth"] = {
        "type": "apiKey",
        "in": "header",
        "name": "X-API-Key",
        "description": "API key for system authentication. Get your API key when registering a system.",
    }

    app.openapi_schema = openapi_schema
    return app.openapi_schema


# Override OpenAPI schema to include security scheme
app.openapi = custom_openapi

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Configure appropriately for production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Import routes (must be after app creation)
from zfs_sync.api.routes import (  # noqa: E402
    conflicts,
    dashboard,
    health,
    snapshots,
    sync,
    sync_groups,
    systems,
)

# Validate settings.api_prefix
if not hasattr(settings, "api_prefix") or settings.api_prefix is None:
    raise ValueError(f"settings.api_prefix is not set. Current settings: {dir(settings)}")

# Validate and include routers with error handling
routers_to_include = [
    ("health", health, "Health"),
    ("systems", systems, "Systems"),
    ("snapshots", snapshots, "Snapshots"),
    ("sync_groups", sync_groups, "Sync Groups"),
    ("sync", sync, "Sync"),
    ("conflicts", conflicts, "Conflicts"),
]

for route_name, route_module, tag in routers_to_include:
    try:
        if not hasattr(route_module, "router"):
            raise AttributeError(
                f"Module {route_name} does not have a 'router' attribute. "
                f"Available attributes: {dir(route_module)}"
            )
        router = route_module.router
        if router is None:
            raise ValueError(f"Router for {route_name} is None")
        app.include_router(router, prefix=settings.api_prefix, tags=[tag])
        logger.debug("Successfully included router: %s", route_name)
    except Exception as exc:
        logger.error("Failed to include router %s: %s", route_name, exc)
        raise RuntimeError(
            f"Failed to include router '{route_name}': {exc}. "
            f"This is a configuration error that must be fixed."
        ) from exc


# Root route - redirect to API docs
@app.get("/")
async def root():
    """Redirect root to dashboard."""
    return RedirectResponse(url="/dashboard")


# Static file serving (for future frontend assets)
# Create static directory if it doesn't exist
static_dir = Path(__file__).parent.parent.parent / "static"
static_dir.mkdir(exist_ok=True)
assets_dir = static_dir / "assets"

# Track if assets are mounted
assets_mounted = False

# Mount static files if directories exist
if assets_dir.exists() and any(assets_dir.iterdir()):
    try:
        app.mount("/assets", StaticFiles(directory=str(assets_dir)), name="assets")
        logger.info("Mounted static assets from %s", assets_dir)
        assets_mounted = True
    except (RuntimeError, OSError) as exc:
        logger.warning("Could not mount assets directory: %s", exc)

if static_dir.exists() and any(static_dir.iterdir()):
    try:
        app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")
        logger.info("Mounted static files from %s", static_dir)
    except (RuntimeError, OSError) as exc:
        logger.warning("Could not mount static directory: %s", exc)


# Handle favicon requests gracefully
@app.get("/favicon.ico")
async def favicon():
    """Handle favicon requests."""
    from fastapi.responses import Response

    return Response(status_code=204)  # No content


# Include the dashboard router without a prefix
app.include_router(dashboard.router, tags=["Dashboard"])

# Catch-all for assets if not mounted (returns 204 to avoid 404 spam in logs)
if not assets_mounted:

    @app.get("/assets/{path:path}")
    async def assets_catchall(_path: str):
        """Handle asset requests when assets directory is not available."""
        from fastapi.responses import Response

        return Response(status_code=204)  # No content
