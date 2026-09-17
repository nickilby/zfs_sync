"""Snapshot management endpoints."""

from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from zfs_sync.api.middleware.auth import get_current_system
from zfs_sync.api.schemas.snapshot import (
    SnapshotBatchResponse,
    SnapshotCreate,
    SnapshotDeleteResponse,
    SnapshotIngestFailure,
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
    "/snapshots/batch",
    response_model=SnapshotBatchResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_snapshots_batch(
    snapshots: List[SnapshotCreate],
    reconcile: bool = Query(
        False,
        description=(
            "Treat this batch as the COMPLETE inventory for the pool/dataset "
            "pairs it mentions, and delete recorded snapshots within those that "
            "are absent from it. Leave false when sending a partial or chunked "
            "report."
        ),
    ),
    db: Session = Depends(get_db),
    current_system: UUID = Depends(get_current_system),
):
    """Report a snapshot inventory.

    Idempotent: reporting the same inventory repeatedly stores it once. The
    previous implementation called ``create()`` per row with no uniqueness, so
    every polling cycle multiplied the records.

    Deletion is opt-in, and this is the important part. Reconciliation used to
    happen on every batch and was scoped to the whole system: anything not in
    the batch was deleted. The shipped reporting script chunks large inventories
    by row count, so on any fleet above the chunk size each chunk deleted what
    the previous chunk had just written, leaving only the final chunk on record.

    With ``reconcile=true`` the caller asserts that this batch is the complete
    inventory for the pool/dataset pairs it mentions, and pruning is confined to
    those. A client that chunks must either chunk on dataset boundaries or leave
    ``reconcile`` false.
    """
    if not snapshots:
        logger.info("Empty snapshot batch received; nothing to do")
        return SnapshotBatchResponse(created=0, updated=0, deleted=0)

    foreign = {s.system_id for s in snapshots if s.system_id != current_system}
    if foreign:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                "A system may only report its own snapshots. This key belongs to "
                f"{current_system}, but the batch contains {len(foreign)} other system(s)."
            ),
        )

    system_repo = SystemRepository(db)
    if not system_repo.get(current_system):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"System {current_system} does not exist",
        )

    repo = SnapshotRepository(db)
    stored: List[SnapshotResponse] = []
    failures: List[SnapshotIngestFailure] = []
    created_count = 0
    updated_count = 0

    # What this report covers. Only these datasets are reconciled.
    scope: set = set()
    reported: set = set()

    for index, snapshot_data in enumerate(snapshots):
        fields = snapshot_data.model_dump(by_alias=True)
        try:
            row, was_created = repo.upsert(**fields)
        except Exception as exc:
            logger.warning(
                "Rejected snapshot %d/%d (%s/%s@%s): %s",
                index + 1,
                len(snapshots),
                snapshot_data.pool,
                snapshot_data.dataset,
                snapshot_data.name,
                exc,
            )
            failures.append(
                SnapshotIngestFailure(
                    name=snapshot_data.name,
                    pool=snapshot_data.pool,
                    dataset=snapshot_data.dataset,
                    error=str(exc),
                )
            )
            continue

        created_count += int(was_created)
        updated_count += int(not was_created)
        stored.append(SnapshotResponse.model_validate(row))
        scope.add((snapshot_data.pool, snapshot_data.dataset))
        reported.add((snapshot_data.pool, snapshot_data.dataset, snapshot_data.name))

    deleted_count, deleted_keys = 0, []
    if reconcile:
        deleted_count, deleted_keys = repo.delete_snapshots_not_in_set(
            current_system, reported, scope=scope
        )
    if deleted_count:
        logger.info(
            "Pruned %d snapshot(s) no longer reported for system %s: %s",
            deleted_count,
            current_system,
            ", ".join(f"{pool}/{dataset}@{name}" for pool, dataset, name in deleted_keys[:10]),
        )

    logger.info(
        "Snapshot report for system %s: %d created, %d updated, %d deleted, %d failed "
        "across %d dataset(s)%s",
        current_system,
        created_count,
        updated_count,
        deleted_count,
        len(failures),
        len(scope),
        "" if reconcile else " (reconcile=false, nothing pruned)",
    )

    return SnapshotBatchResponse(
        created=created_count,
        updated=updated_count,
        deleted=deleted_count,
        failed=failures,
        scope=sorted(f"{pool}/{dataset}" for pool, dataset in scope),
        snapshots=stored,
    )


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
    dataset: str = Query(..., description="Dataset name (pool-agnostic, e.g., 'DATA1')"),
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
