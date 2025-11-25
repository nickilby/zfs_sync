"""Health check endpoints."""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import text
from sqlalchemy.orm import Session

from zfs_sync.config import get_settings
from zfs_sync.database import get_db
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
async def readiness_check(db: Session = Depends(get_db)):
    """Readiness check endpoint with database connectivity verification."""
    try:
        # Test database connectivity with a simple query
        db.execute(text("SELECT 1"))
        return {
            "status": "ready",
            "database": "connected",
            "service": settings.app_name,
        }
    except Exception as e:
        logger.error(f"Database connectivity check failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Database not available: {str(e)}"
        )


@router.get("/health/live")
async def liveness_check():
    """Liveness check endpoint."""
    return {"status": "alive"}

