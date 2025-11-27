"""System management endpoints."""

from typing import Dict, List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from zfs_sync.api.middleware.auth import get_current_system, get_optional_system
from zfs_sync.api.schemas.system import SystemCreate, SystemResponse, SystemUpdate
from zfs_sync.database import get_db
from zfs_sync.database.repositories import SystemRepository
from zfs_sync.logging_config import get_logger
from zfs_sync.services.auth import AuthService
from zfs_sync.services.system_health import SystemHealthService

logger = get_logger(__name__)
router = APIRouter()


@router.post("/systems", response_model=SystemResponse, status_code=status.HTTP_201_CREATED)
async def create_system(system: SystemCreate, db: Session = Depends(get_db)):
    """Register a new system. An API key will be automatically generated."""
    repo = SystemRepository(db)
    existing = repo.get_by_hostname(system.hostname)
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"System with hostname '{system.hostname}' already exists (ID: {existing.id})",
        )
    try:
        db_system = repo.create(**system.model_dump(by_alias=True))
    except ValueError as e:
        # Handle constraint violations from repository
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=f"Failed to create system: {str(e)}"
        ) from e

    # Generate API key for the new system
    try:
        auth_service = AuthService(db)
        api_key = auth_service.create_api_key_for_system(db_system.id)
    except ValueError as e:
        logger.error(f"Failed to generate API key for system {db_system.id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"System created but failed to generate API key: {str(e)}",
        ) from e

    logger.info(f"Created system: {db_system.hostname} ({db_system.id}) with API key")
    response = SystemResponse.model_validate(db_system)
    # Include API key only on creation (security: key is only shown once)
    response.api_key = api_key
    return response


@router.post("/systems/{system_id}/api-key", status_code=status.HTTP_200_OK)
async def generate_api_key(
    system_id: UUID,
    db: Session = Depends(get_db),
    current_system: UUID = Depends(get_current_system),
):
    """Generate a new API key for a system. Requires authentication."""
    # Only allow system to generate its own key, or admin access (future: add admin role)
    if current_system != system_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Can only generate API key for your own system",
        )

    auth_service = AuthService(db)
    api_key = auth_service.create_api_key_for_system(system_id)
    logger.info(f"Generated new API key for system {system_id}")
    return {"api_key": api_key, "system_id": str(system_id)}


@router.delete("/systems/{system_id}/api-key", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_api_key(
    system_id: UUID,
    db: Session = Depends(get_db),
    current_system: UUID = Depends(get_current_system),
):
    """Revoke API key for a system. Requires authentication."""
    if current_system != system_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Can only revoke API key for your own system",
        )

    auth_service = AuthService(db)
    auth_service.revoke_api_key(system_id)
    logger.info(f"Revoked API key for system {system_id}")


@router.post("/systems/{system_id}/api-key/rotate", status_code=status.HTTP_200_OK)
async def rotate_api_key(
    system_id: UUID,
    db: Session = Depends(get_db),
    current_system: UUID = Depends(get_current_system),
):
    """Rotate (generate new) API key for a system. Requires authentication."""
    if current_system != system_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Can only rotate API key for your own system",
        )

    auth_service = AuthService(db)
    new_api_key = auth_service.rotate_api_key(system_id)
    logger.info(f"Rotated API key for system {system_id}")
    return {"api_key": new_api_key, "system_id": str(system_id)}


@router.get("/systems", response_model=List[SystemResponse])
async def list_systems(skip: int = 0, limit: int = 100, db: Session = Depends(get_db)):
    """List all registered systems."""
    repo = SystemRepository(db)
    systems = repo.get_all(skip=skip, limit=limit)

    results = []
    for system in systems:
        try:
            response = SystemResponse.model_validate(system)
            results.append(response)
        except Exception as e:
            logger.error(
                f"Failed to validate system {system.id} ({system.hostname}): {e}", exc_info=True
            )
            # Continue with other systems even if one fails
            continue

    logger.info(
        f"Returning {len(results)} systems (requested {len(systems)}, skipped {len(systems) - len(results)})"
    )
    return results


@router.get("/systems/{system_id}", response_model=SystemResponse)
async def get_system(system_id: UUID, db: Session = Depends(get_db)):
    """Get a system by ID."""
    repo = SystemRepository(db)
    system = repo.get(system_id)
    if not system:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"System with ID '{system_id}' not found"
        )
    return SystemResponse.model_validate(system)


@router.put("/systems/{system_id}", response_model=SystemResponse)
async def update_system(
    system_id: UUID, system_update: SystemUpdate, db: Session = Depends(get_db)
):
    """Update a system."""
    repo = SystemRepository(db)
    try:
        system = repo.update(
            system_id, **system_update.model_dump(exclude_unset=True, by_alias=True)
        )
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to update system '{system_id}': {str(e)}",
        ) from e
    if not system:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"System with ID '{system_id}' not found"
        )
    logger.info(f"Updated system: {system.hostname} ({system.id})")
    return SystemResponse.model_validate(system)


@router.delete("/systems/{system_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_system(system_id: UUID, db: Session = Depends(get_db)):
    """Delete a system."""
    repo = SystemRepository(db)
    try:
        if not repo.delete(system_id):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"System with ID '{system_id}' not found",
            )
    except Exception as e:
        if isinstance(e, HTTPException):
            raise
        logger.error(f"Error deleting system {system_id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to delete system '{system_id}': {str(e)}",
        ) from e
    logger.info(f"Deleted system: {system_id}")


@router.post("/systems/{system_id}/heartbeat", status_code=status.HTTP_200_OK)
async def record_heartbeat(
    system_id: UUID,
    metadata: Optional[Dict] = None,
    db: Session = Depends(get_db),
    current_system: UUID = Depends(get_current_system),
):
    """Record a heartbeat from a system. Requires authentication."""
    if current_system != system_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Can only record heartbeat for your own system",
        )

    health_service = SystemHealthService(db)
    result = health_service.record_heartbeat(system_id=system_id, metadata=metadata)
    return result


@router.get("/systems/{system_id}/health")
async def get_system_health(
    system_id: UUID,
    db: Session = Depends(get_db),
    current_system: Optional[UUID] = Depends(get_optional_system),
):
    """Get health status for a system. Public endpoint."""
    health_service = SystemHealthService(db)
    health = health_service.check_system_health(system_id)
    return health


@router.get("/systems/health/all")
async def get_all_systems_health(db: Session = Depends(get_db)):
    """Get health status for all systems. Public endpoint."""
    health_service = SystemHealthService(db)
    all_health = health_service.get_all_systems_health()
    return {"systems": all_health, "count": len(all_health)}


@router.get("/systems/health/online")
async def get_online_systems(db: Session = Depends(get_db)):
    """Get list of online systems. Public endpoint."""
    health_service = SystemHealthService(db)
    online = health_service.get_online_systems()
    return {"systems": online, "count": len(online)}


@router.get("/systems/health/offline")
async def get_offline_systems(db: Session = Depends(get_db)):
    """Get list of offline systems. Public endpoint."""
    health_service = SystemHealthService(db)
    offline = health_service.get_offline_systems()
    return {"systems": offline, "count": len(offline)}
