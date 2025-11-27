"""Synchronization coordination endpoints."""

from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from zfs_sync.api.schemas.sync import (
    SyncStateResponse,
    SyncActionResponse,
    SyncStatusSummary,
    SyncInstructionsResponse,
)
from zfs_sync.database import get_db
from zfs_sync.database.repositories import SyncStateRepository
from zfs_sync.logging_config import get_logger
from zfs_sync.models import SyncStatus
from zfs_sync.services.sync_coordination import SyncCoordinationService

logger = get_logger(__name__)
router = APIRouter()


@router.get("/sync/states", response_model=List[SyncStateResponse])
async def list_sync_states(skip: int = 0, limit: int = 100, db: Session = Depends(get_db)):
    """List all synchronization states."""
    repo = SyncStateRepository(db)
    states = repo.get_all(skip=skip, limit=limit)
    return [SyncStateResponse.model_validate(s) for s in states]


@router.get("/sync/states/{state_id}", response_model=SyncStateResponse)
async def get_sync_state(state_id: UUID, db: Session = Depends(get_db)):
    """Get a sync state by ID."""
    repo = SyncStateRepository(db)
    state = repo.get(state_id)
    if not state:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Sync state not found")
    return SyncStateResponse.model_validate(state)


@router.get("/sync/groups/{group_id}/states", response_model=List[SyncStateResponse])
async def get_sync_states_by_group(group_id: UUID, db: Session = Depends(get_db)):
    """Get all sync states for a sync group."""
    repo = SyncStateRepository(db)
    states = repo.get_by_sync_group(group_id)
    return [SyncStateResponse.model_validate(s) for s in states]


@router.get("/sync/groups/{group_id}/mismatches")
async def get_sync_mismatches(group_id: UUID, db: Session = Depends(get_db)):
    """Detect snapshot mismatches for a sync group."""
    service = SyncCoordinationService(db)
    mismatches = service.detect_sync_mismatches(sync_group_id=group_id)
    return {"mismatches": mismatches, "count": len(mismatches)}


@router.get("/sync/groups/{group_id}/actions", response_model=List[SyncActionResponse])
async def get_sync_actions(
    group_id: UUID,
    system_id: Optional[UUID] = Query(None, description="Filter actions for specific system"),
    db: Session = Depends(get_db),
):
    """Get sync actions needed for a sync group."""
    service = SyncCoordinationService(db)
    actions = service.determine_sync_actions(sync_group_id=group_id, system_id=system_id)
    return [SyncActionResponse(**action) for action in actions]


@router.get("/sync/instructions/{system_id}", response_model=SyncInstructionsResponse)
async def get_sync_instructions(
    system_id: UUID,
    sync_group_id: Optional[UUID] = Query(None, description="Filter by sync group"),
    db: Session = Depends(get_db),
):
    """Get sync instructions for a system (dataset-grouped format)."""
    service = SyncCoordinationService(db)
    instructions = service.get_sync_instructions(system_id=system_id, sync_group_id=sync_group_id)
    return SyncInstructionsResponse(**instructions)


@router.post("/sync/states", response_model=SyncStateResponse, status_code=status.HTTP_201_CREATED)
async def create_or_update_sync_state(
    sync_group_id: UUID,
    snapshot_id: UUID,
    system_id: UUID,
    status: SyncStatus,
    error_message: Optional[str] = None,
    db: Session = Depends(get_db),
):
    """Create or update a sync state."""
    service = SyncCoordinationService(db)
    sync_state = service.update_sync_state(
        sync_group_id=sync_group_id,
        snapshot_id=snapshot_id,
        system_id=system_id,
        status=status,
        error_message=error_message,
    )
    return SyncStateResponse.model_validate(sync_state)


@router.get("/sync/groups/{group_id}/status", response_model=SyncStatusSummary)
async def get_sync_status_summary(group_id: UUID, db: Session = Depends(get_db)):
    """Get sync status summary for a sync group."""
    service = SyncCoordinationService(db)
    summary = service.get_sync_status_summary(sync_group_id=group_id)
    return SyncStatusSummary(**summary)
