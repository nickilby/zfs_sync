"""Repository for Snapshot operations."""

from typing import List, Optional, Sequence, Set, Tuple
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

    def get_for_systems(self, system_ids: Sequence[UUID]) -> List[SnapshotModel]:
        """Fetch every snapshot for several systems in one query.

        The planner needs the whole picture for a sync group at once. Doing
        that per dataset per system is what made planning scale with the
        dataset count: the old coordination service loaded every snapshot row
        for every system just to collect distinct dataset names, then re-issued
        get_by_dataset four or more times for each (dataset, target) pair.

        Args:
            system_ids: Systems to fetch snapshots for.

        Returns:
            All snapshots belonging to those systems, ordered by timestamp.
        """
        if not system_ids:
            return []
        return (
            self.db.query(SnapshotModel)
            .filter(SnapshotModel.system_id.in_(list(system_ids)))
            .order_by(SnapshotModel.timestamp.asc())
            .all()
        )

    def get_by_dataset(self, dataset: str, system_id: Optional[UUID] = None) -> List[SnapshotModel]:
        """Get snapshots by dataset, across all pools."""
        query = self.db.query(SnapshotModel).filter(SnapshotModel.dataset == dataset)
        if system_id:
            query = query.filter(SnapshotModel.system_id == system_id)
        return query.all()

    def upsert(self, **fields) -> Tuple[SnapshotModel, bool]:
        """Create a snapshot, or update the existing row with the same identity.

        A snapshot is identified by ``(system_id, pool, dataset, name)``. Clients
        report their whole inventory on every cycle, so ingestion must be
        idempotent: it previously called ``create()`` unconditionally, which
        multiplied the rows on every poll.

        Returns:
            The row, and whether it was newly created.
        """
        existing = (
            self.db.query(SnapshotModel)
            .filter(
                SnapshotModel.system_id == fields["system_id"],
                SnapshotModel.pool == fields["pool"],
                SnapshotModel.dataset == fields["dataset"],
                SnapshotModel.name == fields["name"],
            )
            .first()
        )

        if existing is None:
            return self.create(**fields), True

        # Refresh the mutable facts; identity fields are what matched.
        for key, value in fields.items():
            if key not in {"system_id", "pool", "dataset", "name"}:
                setattr(existing, key, value)
        self.db.commit()
        self.db.refresh(existing)
        return existing, False

    def delete_snapshots_not_in_set(
        self,
        system_id: UUID,
        reported_snapshots: Set[Tuple[str, str, str]],
        scope: Optional[Set[Tuple[str, str]]] = None,
    ) -> tuple[int, List[Tuple[str, str, str]]]:
        """
        Delete snapshots for a system that the client did not report.

        Args:
            system_id: System UUID.
            reported_snapshots: ``(pool, dataset, name)`` tuples the client just
                reported.
            scope: ``(pool, dataset)`` pairs the report actually covered. Only
                snapshots within these are eligible for deletion.

                This argument exists because the reconciliation was previously
                system-wide: anything absent from the batch was deleted, so a
                client reporting a single dataset -- or a paginated report, or a
                run that crashed part way -- destroyed the rest of that system's
                recorded history. That history is what incremental bases are
                computed from. ``None`` preserves the old system-wide behaviour
                and should only be used by a caller that genuinely reported
                everything.

        Returns:
            Tuple of (count deleted, list of deleted ``(pool, dataset, name)``).
        """
        existing = self.get_by_system(system_id, skip=0, limit=None)

        to_delete = []
        deleted_keys = []
        for snapshot in existing:
            if scope is not None and (snapshot.pool, snapshot.dataset) not in scope:
                # The client said nothing about this dataset, so its absence
                # from the report is not evidence that it is gone.
                continue
            key = (snapshot.pool, snapshot.dataset, snapshot.name)
            if key not in reported_snapshots:
                to_delete.append(snapshot.id)
                deleted_keys.append(key)

        if to_delete:
            count = (
                self.db.query(SnapshotModel)
                .filter(SnapshotModel.id.in_(to_delete))
                .delete(synchronize_session=False)
            )
            self.db.commit()
            return count, deleted_keys

        return 0, []
