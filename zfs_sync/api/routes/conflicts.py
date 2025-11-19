"""Conflict resolution endpoints."""

from typing import List
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from zfs_sync.api.schemas.conflict import (
    ConflictListResponse,
    ConflictResolutionRequest,
    ConflictResolutionResponse,
    ConflictResponse,
)
from zfs_sync.database import get_db
from zfs_sync.logging_config import get_logger
from zfs_sync.services.conflict_resolution import ConflictResolutionService

logger = get_logger(__name__)
router = APIRouter()


@router.get("/conflicts/sync-group/{sync_group_id}", response_model=ConflictListResponse)
async def get_all_conflicts(
    sync_group_id: UUID,
    db: Session = Depends(get_db),
):
    """Get all conflicts for a sync group."""
    service = ConflictResolutionService(db)
    conflicts = service.get_all_conflicts(sync_group_id)
    return ConflictListResponse(
        conflicts=[ConflictResponse(**c) for c in conflicts],
        count=len(conflicts),
        sync_group_id=str(sync_group_id),
    )


@router.get("/conflicts/dataset", response_model=List[ConflictResponse])
async def get_conflicts_for_dataset(
    sync_group_id: UUID = Query(..., description="Sync group ID"),
    pool: str = Query(..., description="ZFS pool name"),
    dataset: str = Query(..., description="ZFS dataset name"),
    mark_in_states: bool = Query(False, description="Mark conflicts in sync states"),
    db: Session = Depends(get_db),
):
    """Detect conflicts for a specific dataset."""
    service = ConflictResolutionService(db)
    conflicts = service.detect_conflicts(sync_group_id, pool, dataset)

    # Optionally mark conflicts in sync states
    if mark_in_states and conflicts:
        service.mark_conflicts_in_sync_states(sync_group_id, conflicts)

    return [ConflictResponse(**c) for c in conflicts]


@router.post(
    "/conflicts/resolve",
    response_model=ConflictResolutionResponse,
    status_code=status.HTTP_200_OK,
)
async def resolve_conflict(
    conflict: ConflictResponse,
    resolution: ConflictResolutionRequest,
    db: Session = Depends(get_db),
):
    """Resolve a conflict using the specified strategy."""
    service = ConflictResolutionService(db)

    conflict_dict = conflict.model_dump()
    result = service.resolve_conflict(
        conflict=conflict_dict,
        strategy=resolution.strategy,
        resolution_data=resolution.resolution_data,
    )

    # If resolution requires manual intervention, return that status
    if result.get("status") == "requires_manual_intervention":
        return ConflictResolutionResponse(
            status="requires_manual_intervention",
            conflict=conflict_dict,
            message=result.get("message"),
        )

    # If auto-resolved, mark as resolved
    if result.get("status") == "resolved":
        # Generate a conflict ID (in production, this would be stored)
        conflict_id = f"{conflict.sync_group_id}:{conflict.pool}:{conflict.dataset}:{conflict.snapshot_name}"
        service.mark_conflict_resolved(conflict_id, result)

    return ConflictResolutionResponse(**result)


@router.get("/conflicts/summary/{sync_group_id}")
async def get_conflict_summary(
    sync_group_id: UUID,
    db: Session = Depends(get_db),
):
    """Get a summary of conflicts for a sync group."""
    service = ConflictResolutionService(db)
    conflicts = service.get_all_conflicts(sync_group_id)

    # Group by type and severity
    by_type = {}
    by_severity = {"low": 0, "medium": 0, "high": 0}

    for conflict in conflicts:
        conflict_type = conflict.get("type")
        severity = conflict.get("severity", "unknown")

        by_type[conflict_type] = by_type.get(conflict_type, 0) + 1
        by_severity[severity] = by_severity.get(severity, 0) + 1

    return {
        "sync_group_id": str(sync_group_id),
        "total_conflicts": len(conflicts),
        "by_type": by_type,
        "by_severity": by_severity,
        "conflicts": conflicts,
    }


@router.post("/conflicts/{conflict_id}/mark-resolved")
async def mark_conflict_as_resolved(
    conflict_id: str,
    resolution: ConflictResolutionResponse,
    resolved_by: str = Query(None, description="Who resolved the conflict"),
    db: Session = Depends(get_db),
):
    """Manually mark a conflict as resolved."""
    service = ConflictResolutionService(db)

    # Extract conflict from resolution
    conflict_dict = resolution.conflict or {}
    result = service.mark_conflict_resolved(
        conflict_id=conflict_id,
        resolution=resolution.model_dump(),
        resolved_by=resolved_by,
    )

    return {
        "status": "success",
        "message": f"Conflict {conflict_id} marked as resolved",
        "resolution": result,
    }

