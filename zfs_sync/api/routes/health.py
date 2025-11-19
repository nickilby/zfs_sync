"""Health check endpoints."""

from fastapi import APIRouter

from zfs_sync.config import get_settings
from zfs_sync.logging_config import get_logger

logger = get_logger(__name__)
router = APIRouter()
settings = get_settings()


@router.get("/health")
async def health_check():
    """Health check endpoint."""
    return {
        "status": "healthy",
        "service": settings.app_name,
        "version": settings.app_version,
    }


@router.get("/health/ready")
async def readiness_check():
    """Readiness check endpoint."""
    # TODO: Add database connectivity check
    return {"status": "ready"}


@router.get("/health/live")
async def liveness_check():
    """Liveness check endpoint."""
    return {"status": "alive"}

