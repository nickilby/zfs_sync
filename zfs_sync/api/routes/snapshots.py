"""Snapshot management endpoints."""

from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from zfs_sync.api.schemas.snapshot import SnapshotCreate, SnapshotResponse
from zfs_sync.database import get_db
from zfs_sync.database.repositories import SnapshotRepository
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


@router.get("/snapshots/{snapshot_id}", response_model=SnapshotResponse)
async def get_snapshot(snapshot_id: UUID, db: Session = Depends(get_db)):
    """Get a snapshot by ID."""
    repo = SnapshotRepository(db)
    snapshot = repo.get(snapshot_id)
    if not snapshot:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Snapshot not found")
    return SnapshotResponse.model_validate(snapshot)


@router.get("/snapshots/system/{system_id}", response_model=List[SnapshotResponse])
async def get_snapshots_by_system(
    system_id: UUID,
    skip: int = 0,
    limit: int = 100,
    pool: Optional[str] = None,
    dataset: Optional[str] = None,
    db: Session = Depends(get_db),
):
    """Get all snapshots for a system with optional filters."""
    repo = SnapshotRepository(db)
    if pool and dataset:
        snapshots = repo.get_by_pool_dataset(pool=pool, dataset=dataset, system_id=system_id)
    else:
        snapshots = repo.get_by_system(system_id, skip=skip, limit=limit)
    return [SnapshotResponse.model_validate(s) for s in snapshots]


@router.post("/snapshots/batch", response_model=List[SnapshotResponse], status_code=status.HTTP_201_CREATED)
async def create_snapshots_batch(
    snapshots: List[SnapshotCreate], db: Session = Depends(get_db)
):
    """Report multiple snapshots in a single request."""
    repo = SnapshotRepository(db)
    created = []
    for snapshot_data in snapshots:
        db_snapshot = repo.create(**snapshot_data.model_dump(by_alias=True))
        created.append(SnapshotResponse.model_validate(db_snapshot))
    logger.info(f"Created {len(created)} snapshots in batch")
    return created


@router.get("/snapshots/compare")
async def compare_snapshots(
    pool: str = Query(..., description="ZFS pool name"),
    dataset: str = Query(..., description="ZFS dataset name"),
    system_ids: List[UUID] = Query(..., description="System IDs to compare"),
    db: Session = Depends(get_db),
):
    """Compare snapshots across multiple systems for a dataset."""
    service = SnapshotComparisonService(db)
    result = service.compare_snapshots_by_dataset(pool=pool, dataset=dataset, system_ids=system_ids)
    return result


@router.get("/snapshots/differences")
async def get_snapshot_differences(
    system_id_1: UUID = Query(..., description="First system ID"),
    system_id_2: UUID = Query(..., description="Second system ID"),
    pool: str = Query(..., description="ZFS pool name"),
    dataset: str = Query(..., description="ZFS dataset name"),
    db: Session = Depends(get_db),
):
    """Find differences between snapshots on two systems."""
    service = SnapshotComparisonService(db)
    result = service.find_snapshot_differences(
        system_id_1=system_id_1,
        system_id_2=system_id_2,
        pool=pool,
        dataset=dataset,
    )
    return result


@router.get("/snapshots/gaps")
async def get_snapshot_gaps(
    pool: str = Query(..., description="ZFS pool name"),
    dataset: str = Query(..., description="ZFS dataset name"),
    system_ids: List[UUID] = Query(..., description="System IDs to check"),
    db: Session = Depends(get_db),
):
    """Identify gaps in snapshot sequences across systems."""
    service = SnapshotComparisonService(db)
    gaps = service.get_snapshot_gaps(system_ids=system_ids, pool=pool, dataset=dataset)
    return {"gaps": gaps, "count": len(gaps)}


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


@router.get("/snapshots/timeline")
async def get_snapshot_timeline(
    pool: str = Query(..., description="ZFS pool name"),
    dataset: str = Query(..., description="ZFS dataset name"),
    system_ids: List[UUID] = Query(..., description="System IDs"),
    db: Session = Depends(get_db),
):
    """Get a timeline of snapshots across multiple systems."""
    service = SnapshotHistoryService(db)
    timeline = service.get_snapshot_timeline(
        pool=pool, dataset=dataset, system_ids=system_ids
    )
    return timeline


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

