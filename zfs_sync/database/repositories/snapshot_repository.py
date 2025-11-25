"""Repository for Snapshot operations."""

from typing import List, Optional
from uuid import UUID

from sqlalchemy.orm import Session

from zfs_sync.database.models import SnapshotModel
from zfs_sync.database.repositories.base_repository import BaseRepository


class SnapshotRepository(BaseRepository[SnapshotModel]):
    """Repository for Snapshot database operations."""

    def __init__(self, db: Session):
        """Initialize snapshot repository."""
        super().__init__(SnapshotModel, db)

    def get_by_system(self, system_id: UUID, skip: int = 0, limit: int = 100) -> List[SnapshotModel]:
        """Get all snapshots for a system."""
        return (
            self.db.query(SnapshotModel)
            .filter(SnapshotModel.system_id == system_id)
            .offset(skip)
            .limit(limit)
            .all()
        )

    def get_by_pool_dataset(
        self, pool: str, dataset: str, system_id: Optional[UUID] = None
    ) -> List[SnapshotModel]:
        """Get snapshots by pool and dataset."""
        query = self.db.query(SnapshotModel).filter(
            SnapshotModel.pool == pool, SnapshotModel.dataset == dataset
        )
        if system_id:
            query = query.filter(SnapshotModel.system_id == system_id)
        return query.all()

    def get_latest_by_dataset(
        self, pool: str, dataset: str, system_id: UUID
    ) -> Optional[SnapshotModel]:
        """Get the latest snapshot for a dataset."""
        return (
            self.db.query(SnapshotModel)
            .filter(
                SnapshotModel.pool == pool,
                SnapshotModel.dataset == dataset,
                SnapshotModel.system_id == system_id,
            )
            .order_by(SnapshotModel.timestamp.desc())
            .first()
        )

