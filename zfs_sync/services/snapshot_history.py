"""Service for tracking snapshot history and changes."""

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
from uuid import UUID

from sqlalchemy import and_, desc
from sqlalchemy.orm import Session

from zfs_sync.database.models import SnapshotModel
from zfs_sync.database.repositories import SnapshotRepository
from zfs_sync.logging_config import get_logger

logger = get_logger(__name__)


class SnapshotHistoryService:
    """Service for tracking and querying snapshot history."""

    def __init__(self, db: Session):
        """Initialize the history service."""
        self.db = db
        self.snapshot_repo = SnapshotRepository(db)

    def get_snapshot_history(
        self,
        system_id: UUID,
        pool: Optional[str] = None,
        dataset: Optional[str] = None,
        days: Optional[int] = None,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        """
        Get snapshot history for a system with optional filters.

        Args:
            system_id: System to get history for
            pool: Optional pool filter
            dataset: Optional dataset filter
            days: Optional number of days to look back
            limit: Maximum number of results

        Returns:
            List of snapshot history entries
        """
        query = self.db.query(SnapshotModel).filter(SnapshotModel.system_id == system_id)

        if pool:
            query = query.filter(SnapshotModel.pool == pool)
        if dataset:
            query = query.filter(SnapshotModel.dataset == dataset)
        if days:
            cutoff_date = datetime.now(timezone.utc) - timedelta(days=days)
            query = query.filter(SnapshotModel.timestamp >= cutoff_date)

        snapshots = query.order_by(desc(SnapshotModel.timestamp)).limit(limit).all()

        return [
            {
                "id": str(snapshot.id),
                "name": snapshot.name,
                "pool": snapshot.pool,
                "dataset": snapshot.dataset,
                "timestamp": snapshot.timestamp.isoformat(),
                "size": snapshot.size,
                "referenced": snapshot.referenced,
                "used": snapshot.used,
                "created_at": snapshot.created_at.isoformat(),
            }
            for snapshot in snapshots
        ]

    def get_snapshot_timeline(
        self, pool: str, dataset: str, system_ids: List[UUID]
    ) -> Dict[str, Any]:
        """
        Get a timeline of snapshots across multiple systems for a dataset.

        Returns snapshots ordered by timestamp with system information.
        """
        all_snapshots = []
        for system_id in system_ids:
            snapshots = self.snapshot_repo.get_by_pool_dataset(
                pool=pool, dataset=dataset, system_id=system_id
            )
            for snapshot in snapshots:
                all_snapshots.append(
                    {
                        "snapshot_id": str(snapshot.id),
                        "name": snapshot.name,
                        "system_id": str(system_id),
                        "timestamp": snapshot.timestamp.isoformat(),
                        "size": snapshot.size,
                    }
                )

        # Sort by timestamp
        all_snapshots.sort(key=lambda x: x["timestamp"])

        return {
            "pool": pool,
            "dataset": dataset,
            "snapshots": all_snapshots,
            "total_count": len(all_snapshots),
            "systems": [str(sid) for sid in system_ids],
        }

    def get_snapshot_statistics(self, system_id: UUID, days: int = 30) -> Dict[str, Any]:
        """
        Get statistics about snapshots for a system.

        Returns counts, sizes, and trends.
        """
        cutoff_date = datetime.now(timezone.utc) - timedelta(days=days)

        snapshots = (
            self.db.query(SnapshotModel)
            .filter(
                and_(
                    SnapshotModel.system_id == system_id,
                    SnapshotModel.timestamp >= cutoff_date,
                )
            )
            .all()
        )

        if not snapshots:
            return {
                "system_id": str(system_id),
                "period_days": days,
                "total_snapshots": 0,
                "total_size": 0,
                "pools": {},
                "datasets": {},
            }

        total_size = sum(s.size or 0 for s in snapshots)
        pools: Dict[str, int] = {}
        datasets: Dict[str, int] = {}

        for snapshot in snapshots:
            pools[snapshot.pool] = pools.get(snapshot.pool, 0) + 1
            dataset_key = f"{snapshot.pool}/{snapshot.dataset}"
            datasets[dataset_key] = datasets.get(dataset_key, 0) + 1

        return {
            "system_id": str(system_id),
            "period_days": days,
            "total_snapshots": len(snapshots),
            "total_size": total_size,
            "average_size": total_size / len(snapshots) if snapshots else 0,
            "pools": pools,
            "datasets": datasets,
            "oldest_snapshot": min(s.timestamp for s in snapshots).isoformat(),
            "newest_snapshot": max(s.timestamp for s in snapshots).isoformat(),
        }

    def track_snapshot_changes(
        self, system_id: UUID, current_snapshots: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """
        Track changes in snapshots by comparing current state with stored state.

        Returns:
            Dictionary with added, removed, and unchanged snapshots
        """
        # Get existing snapshots from database
        existing_snapshots = self.snapshot_repo.get_by_system(system_id)

        existing_names = {f"{s.pool}/{s.dataset}@{s.name}" for s in existing_snapshots}
        current_names = {f"{s['pool']}/{s['dataset']}@{s['name']}" for s in current_snapshots}

        added = current_names - existing_names
        removed = existing_names - current_names
        unchanged = existing_names & current_names

        return {
            "system_id": str(system_id),
            "added_snapshots": sorted(list(added)),
            "removed_snapshots": sorted(list(removed)),
            "unchanged_snapshots": sorted(list(unchanged)),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
