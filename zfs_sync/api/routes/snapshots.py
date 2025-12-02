"""Snapshot management endpoints."""

from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from zfs_sync.api.schemas.snapshot import (
    SnapshotCreate,
    SnapshotDeleteResponse,
    SnapshotResponse,
)
from zfs_sync.database import get_db
from zfs_sync.database.models import SnapshotModel
from zfs_sync.database.repositories import SnapshotRepository, SystemRepository
from zfs_sync.logging_config import get_logger
from zfs_sync.services.snapshot_comparison import SnapshotComparisonService
from zfs_sync.services.snapshot_history import SnapshotHistoryService

logger = get_logger(__name__)
router = APIRouter()


@router.post("/snapshots", response_model=SnapshotResponse, status_code=status.HTTP_201_CREATED)
async def create_snapshot(snapshot: SnapshotCreate, db: Session = Depends(get_db)):
    """Report a new snapshot."""
    repo = SnapshotRepository(db)
    db_snapshot = repo.create(**snapshot.model_dump(by_alias=True))
    logger.info(f"Created snapshot: {db_snapshot.name} on {db_snapshot.pool}/{db_snapshot.dataset}")
    return SnapshotResponse.model_validate(db_snapshot)


@router.get("/snapshots", response_model=List[SnapshotResponse])
async def list_snapshots(skip: int = 0, limit: int = 100, db: Session = Depends(get_db)):
    """List all snapshots."""
    repo = SnapshotRepository(db)
    snapshots = repo.get_all(skip=skip, limit=limit)
    return [SnapshotResponse.model_validate(s) for s in snapshots]


@router.post(
    "/snapshots/batch", response_model=List[SnapshotResponse], status_code=status.HTTP_201_CREATED
)
async def create_snapshots_batch(snapshots: List[SnapshotCreate], db: Session = Depends(get_db)):
    """
    Report multiple snapshots in a single request.

    Validates that all system_ids exist before creating any snapshots.
    Continues processing even if individual snapshots fail, collecting
    both successful and failed snapshots for reporting.
    """
    if not snapshots:
        logger.warning("Empty snapshot batch received")
        return []

    # Validate all system_ids exist before attempting any creates
    system_repo = SystemRepository(db)
    unique_system_ids = {snapshot.system_id for snapshot in snapshots}
    invalid_system_ids = []

    for system_id in unique_system_ids:
        if not system_repo.get(system_id):
            invalid_system_ids.append(str(system_id))

    if invalid_system_ids:
        error_msg = (
            f"Invalid system_id(s) found: {', '.join(invalid_system_ids)}. "
            "These systems do not exist in the database. "
            "This often happens after system re-registration when the system_id changes. "
            "Please update your system configuration with the new system_id."
        )
        logger.error(f"Batch snapshot creation failed: {error_msg}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=error_msg,
        )

    # Process snapshots with individual error handling
    repo = SnapshotRepository(db)
    created = []
    failed = []

    for idx, snapshot_data in enumerate(snapshots):
        try:
            db_snapshot = repo.create(**snapshot_data.model_dump(by_alias=True))
            created.append(SnapshotResponse.model_validate(db_snapshot))
        except ValueError as e:
            # Handle constraint violations (e.g., duplicate snapshots)
            error_detail = str(e)
            logger.warning(
                f"Failed to create snapshot {idx + 1}/{len(snapshots)}: "
                f"{snapshot_data.name} on {snapshot_data.pool}/{snapshot_data.dataset} - {error_detail}"
            )
            failed.append(
                {
                    "snapshot": snapshot_data.name,
                    "pool": snapshot_data.pool,
                    "dataset": snapshot_data.dataset,
                    "error": error_detail,
                }
            )
        except Exception as e:
            # Handle other unexpected errors
            error_detail = str(e)
            logger.error(
                f"Unexpected error creating snapshot {idx + 1}/{len(snapshots)}: "
                f"{snapshot_data.name} on {snapshot_data.pool}/{snapshot_data.dataset} - {error_detail}",
                exc_info=True,
            )
            failed.append(
                {
                    "snapshot": snapshot_data.name,
                    "pool": snapshot_data.pool,
                    "dataset": snapshot_data.dataset,
                    "error": error_detail,
                }
            )

    # Log summary
    logger.info(
        f"Batch snapshot creation completed: {len(created)} successful, {len(failed)} failed out of {len(snapshots)} total"
    )

    if failed:
        logger.warning(f"Failed snapshots: {failed}")

    # Return only successfully created snapshots
    return created


@router.get("/snapshots/compare-dataset")
async def compare_snapshots_by_dataset(
    dataset: str = Query(..., description="ZFS dataset name"),
    system_ids: List[UUID] = Query(..., description="System IDs to compare"),
    db: Session = Depends(get_db),
):
    """Compare snapshots across multiple systems for a dataset."""
    service = SnapshotComparisonService(db)
    result = service.compare_snapshots_by_dataset(dataset=dataset, system_ids=system_ids)
    return result


@router.get("/snapshots/compare-dataset")
async def compare_snapshots_by_dataset_name(
    dataset: str = Query(..., description="Dataset name (pool-agnostic, e.g., 'L1S4DAT1')"),
    system_ids: List[UUID] = Query(..., description="System IDs to compare"),
    db: Session = Depends(get_db),
):
    """
    Compare snapshots for a dataset name across multiple systems (pool-agnostic).

    This endpoint compares snapshots by dataset name only, ignoring pool names.
    Useful when systems use different pool names but have the same datasets.

    Returns for each system:
    - system_id and hostname
    - sync_status: "in_sync", "out_of_sync", or "no_snapshots"
    - last_snapshot: Name of the latest snapshot on that system
    - missing_count: Number of snapshots missing compared to the system with the most snapshots
    """
    service = SnapshotComparisonService(db)
    result = service.compare_snapshots_by_dataset_name(dataset_name=dataset, system_ids=system_ids)
    return result


@router.get("/snapshots/differences")
async def get_snapshot_differences(
    system_id_1: UUID = Query(..., description="First system ID"),
    system_id_2: UUID = Query(..., description="Second system ID"),
    dataset: str = Query(..., description="ZFS dataset name"),
    db: Session = Depends(get_db),
):
    """Find differences between snapshots on two systems."""
    service = SnapshotComparisonService(db)
    result = service.find_snapshot_differences(
        system_id_1=system_id_1,
        system_id_2=system_id_2,
        dataset=dataset,
    )
    return result


@router.get("/snapshots/gaps")
async def get_snapshot_gaps(
    dataset: str = Query(..., description="ZFS dataset name"),
    system_ids: List[UUID] = Query(..., description="System IDs to check"),
    db: Session = Depends(get_db),
):
    """Identify gaps in snapshot sequences across systems."""
    service = SnapshotComparisonService(db)
    gaps = service.get_snapshot_gaps(system_ids=system_ids, dataset=dataset)
    return {"gaps": gaps, "count": len(gaps)}


@router.get("/snapshots/timeline")
async def get_snapshot_timeline(
    pool: str = Query(..., description="ZFS pool name"),
    dataset: str = Query(..., description="ZFS dataset name"),
    system_ids: List[UUID] = Query(..., description="System IDs"),
    db: Session = Depends(get_db),
):
    """Get a timeline of snapshots across multiple systems."""
    service = SnapshotHistoryService(db)
    timeline = service.get_snapshot_timeline(pool=pool, dataset=dataset, system_ids=system_ids)
    return timeline


@router.get("/snapshots/system/{system_id}", response_model=List[SnapshotResponse])
async def get_snapshots_by_system(
    system_id: UUID,
    skip: int = 0,
    limit: int = 100,
    pool: Optional[str] = Query(None, description="Filter by pool"),
    dataset: Optional[str] = Query(None, description="Filter by dataset"),
    db: Session = Depends(get_db),
):
    """Get all snapshots for a system with optional filters."""
    repo = SnapshotRepository(db)
    query = repo.db.query(SnapshotModel).filter(SnapshotModel.system_id == system_id)

    if dataset:
        query = query.filter(SnapshotModel.dataset == dataset)
    if pool:
        query = query.filter(SnapshotModel.pool == pool)

    snapshots = query.order_by(SnapshotModel.timestamp.desc()).offset(skip).limit(limit).all()
    return [SnapshotResponse.model_validate(s) for s in snapshots]


@router.delete(
    "/snapshots/system/{system_id}",
    response_model=SnapshotDeleteResponse,
    status_code=status.HTTP_200_OK,
)
async def delete_snapshots_by_system(
    system_id: UUID,
    db: Session = Depends(get_db),
):
    """
    Delete all snapshots for a system.

    This is useful when a system is re-registered and needs to clean up
    old snapshots associated with a previous system_id.
    """
    # Verify the system exists
    system_repo = SystemRepository(db)
    system = system_repo.get(system_id)
    if not system:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"System {system_id} not found",
        )

    # Delete all snapshots for this system
    snapshot_repo = SnapshotRepository(db)
    deleted_count = snapshot_repo.delete_by_system(system_id)

    logger.info(f"Deleted {deleted_count} snapshots for system {system_id} ({system.hostname})")

    return SnapshotDeleteResponse(
        system_id=str(system_id),
        hostname=system.hostname,
        deleted_count=deleted_count,
        message=f"Deleted {deleted_count} snapshots",
    )


@router.get("/snapshots/history/{system_id}")
async def get_snapshot_history(
    system_id: UUID,
    pool: Optional[str] = Query(None, description="Filter by pool"),
    dataset: Optional[str] = Query(None, description="Filter by dataset"),
    days: Optional[int] = Query(None, description="Number of days to look back"),
    limit: int = Query(100, description="Maximum results"),
    db: Session = Depends(get_db),
):
    """Get snapshot history for a system."""
    service = SnapshotHistoryService(db)
    history = service.get_snapshot_history(
        system_id=system_id, pool=pool, dataset=dataset, days=days, limit=limit
    )
    return {"history": history, "count": len(history)}


@router.get("/snapshots/statistics/{system_id}")
async def get_snapshot_statistics(
    system_id: UUID,
    days: int = Query(30, description="Number of days to analyze"),
    db: Session = Depends(get_db),
):
    """Get statistics about snapshots for a system."""
    service = SnapshotHistoryService(db)
    stats = service.get_snapshot_statistics(system_id=system_id, days=days)
    return stats


@router.get("/snapshots/{snapshot_id}", response_model=SnapshotResponse)
async def get_snapshot(snapshot_id: UUID, db: Session = Depends(get_db)):
    """Get a snapshot by ID."""
    repo = SnapshotRepository(db)
    snapshot = repo.get(snapshot_id)
    if not snapshot:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Snapshot not found")
    return SnapshotResponse.model_validate(snapshot)
