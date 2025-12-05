"""Repository for Snapshot operations."""

from typing import List, Optional, Set, Tuple
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
        self, system_id: UUID, skip: int = 0, limit: Optional[int] = 100
    ) -> List[SnapshotModel]:
        """
        Get all snapshots for a system, ordered by timestamp descending (most recent first).

        Args:
            system_id: System UUID
            skip: Number of records to skip (for pagination)
            limit: Maximum number of records to return (None for all, default 100)

        Returns:
            List of snapshots for the system
        """
        query = (
            self.db.query(SnapshotModel)
            .filter(SnapshotModel.system_id == system_id)
            .order_by(SnapshotModel.timestamp.desc())
        )
        if skip > 0:
            query = query.offset(skip)
        if limit is not None:
            query = query.limit(limit)
        return query.all()

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

    def get_by_dataset(self, dataset: str, system_id: Optional[UUID] = None) -> List[SnapshotModel]:
        """Get snapshots by dataset, across all pools."""
        query = self.db.query(SnapshotModel).filter(SnapshotModel.dataset == dataset)
        if system_id:
            query = query.filter(SnapshotModel.system_id == system_id)
        return query.all()

    def delete_snapshots_not_in_set(
        self, system_id: UUID, reported_snapshots: Set[Tuple[str, str, str]]
    ) -> tuple[int, List[Tuple[str, str, str]]]:
        """
        Delete snapshots for a system that aren't in the reported set.

        Args:
            system_id: System UUID
            reported_snapshots: Set of (pool, dataset, name) tuples representing current snapshots
                               Note: name is stored as-is (e.g., "L1S6DAT1@2025-11-02-000000" or "2025-11-02-000000")

        Returns:
            Tuple of (count of deleted snapshots, list of deleted (pool, dataset, name) tuples)
        """
        # Get all existing snapshots for this system
        existing = self.get_by_system(system_id, skip=0, limit=None)  # Get all, no limit

        # Find snapshots to delete (in DB but not in reported set)
        to_delete = []
        deleted_keys = []
        for snapshot in existing:
            key = (snapshot.pool, snapshot.dataset, snapshot.name)
            if key not in reported_snapshots:
                to_delete.append(snapshot.id)
                deleted_keys.append(key)

        # Delete in bulk
        if to_delete:
            count = (
                self.db.query(SnapshotModel)
                .filter(SnapshotModel.id.in_(to_delete))
                .delete(synchronize_session=False)
            )
            self.db.commit()
            return count, deleted_keys

        return 0, []
