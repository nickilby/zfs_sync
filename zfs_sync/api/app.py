"""FastAPI application setup."""

from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

from zfs_sync.config import get_settings
from zfs_sync.logging_config import get_logger, setup_logging

# Setup logging
setup_logging()
logger = get_logger(__name__)

# Get settings
settings = get_settings()

# Create FastAPI app
app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    description="A witness service to keep ZFS snapshots in sync across different platforms",
    docs_url="/docs",
    redoc_url="/redoc",
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Configure appropriately for production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
async def startup_event():
    """Initialize application on startup."""
    logger.info(f"Starting {settings.app_name} v{settings.app_version}")
    logger.info(f"Debug mode: {settings.debug}")
    logger.info(f"Database: {settings.database_url}")

    # Initialize database
    from zfs_sync.database import init_db

    init_db()
    logger.info("Database initialized")


@app.on_event("shutdown")
async def shutdown_event():
    """Cleanup on shutdown."""
    logger.info(f"Shutting down {settings.app_name}")


# Import routes (must be after app creation)
from zfs_sync.api.routes import conflicts, health, snapshots, sync, sync_groups, systems  # noqa: E402

app.include_router(health.router, prefix=settings.api_prefix, tags=["Health"])
app.include_router(systems.router, prefix=settings.api_prefix, tags=["Systems"])
app.include_router(snapshots.router, prefix=settings.api_prefix, tags=["Snapshots"])
app.include_router(sync_groups.router, prefix=settings.api_prefix, tags=["Sync Groups"])
app.include_router(sync.router, prefix=settings.api_prefix, tags=["Sync"])
app.include_router(conflicts.router, prefix=settings.api_prefix, tags=["Conflicts"])

# Root route - redirect to API docs
@app.get("/")
async def root():
    """Redirect root to API documentation."""
    return RedirectResponse(url="/docs")


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
        logger.info(f"Mounted static assets from {assets_dir}")
        assets_mounted = True
    except Exception as e:
        logger.warning(f"Could not mount assets directory: {e}")

if static_dir.exists() and any(static_dir.iterdir()):
    try:
        app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")
        logger.info(f"Mounted static files from {static_dir}")
    except Exception as e:
        logger.warning(f"Could not mount static directory: {e}")

# Handle favicon requests gracefully
@app.get("/favicon.ico")
async def favicon():
    """Handle favicon requests."""
    from fastapi.responses import Response
    return Response(status_code=204)  # No content


# Catch-all for assets if not mounted (returns 204 to avoid 404 spam in logs)
if not assets_mounted:
    @app.get("/assets/{path:path}")
    async def assets_catchall(path: str):
        """Handle asset requests when assets directory is not available."""
        from fastapi.responses import Response
        return Response(status_code=204)  # No content

