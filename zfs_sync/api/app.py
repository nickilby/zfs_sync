"""FastAPI application setup."""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

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

