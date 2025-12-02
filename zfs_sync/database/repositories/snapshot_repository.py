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

    def get_all(self, skip: int = 0, limit: int = 100) -> List[SnapshotModel]:
        """Get all snapshots with pagination, ordered by timestamp descending (most recent first)."""
        return (
            self.db.query(SnapshotModel)
            .order_by(SnapshotModel.timestamp.desc())
            .offset(skip)
            .limit(limit)
            .all()
        )

    def get_by_system(
        self, system_id: UUID, skip: int = 0, limit: int = 100
    ) -> List[SnapshotModel]:
        """Get all snapshots for a system, ordered by timestamp descending (most recent first)."""
        return (
            self.db.query(SnapshotModel)
            .filter(SnapshotModel.system_id == system_id)
            .order_by(SnapshotModel.timestamp.desc())
            .offset(skip)
            .limit(limit)
            .all()
        )

    def get_by_system_and_dataset(
        self, system_id: UUID, dataset: str, skip: int = 0, limit: Optional[int] = None
    ) -> List[SnapshotModel]:
        """
        Get all snapshots for a system and dataset, ordered by timestamp descending.

        Args:
            system_id: System UUID
            dataset: Dataset name
            skip: Number of records to skip (for pagination)
            limit: Maximum number of records to return (None for all)

        Returns:
            List of snapshots matching the system and dataset
        """
        query = (
            self.db.query(SnapshotModel)
            .filter(SnapshotModel.system_id == system_id, SnapshotModel.dataset == dataset)
            .order_by(SnapshotModel.timestamp.desc())
        )
        if skip > 0:
            query = query.offset(skip)
        if limit:
            query = query.limit(limit)
        return query.all()

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

    def delete_by_system(self, system_id: UUID) -> int:
        """Delete all snapshots for a system. Returns count of deleted snapshots."""
        count = (
            self.db.query(SnapshotModel)
            .filter(SnapshotModel.system_id == system_id)
            .delete(synchronize_session=False)
        )
        self.db.commit()
        return count

    def get_by_dataset(
        self, dataset: str, system_id: Optional[UUID] = None
    ) -> List[SnapshotModel]:
        """Get snapshots by dataset, across all pools."""
        query = self.db.query(SnapshotModel).filter(SnapshotModel.dataset == dataset)
        if system_id:
            query = query.filter(SnapshotModel.system_id == system_id)
        return query.all()

