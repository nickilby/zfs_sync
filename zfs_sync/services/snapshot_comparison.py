"""Service for comparing snapshot states across systems."""

from datetime import datetime, timezone
from typing import Any, Dict, List, Set
from uuid import UUID

from sqlalchemy.orm import Session

from zfs_sync.database.models import SnapshotModel
from zfs_sync.database.repositories import SnapshotRepository
from zfs_sync.logging_config import get_logger

logger = get_logger(__name__)


class SnapshotComparisonService:
    """Service for comparing and analyzing snapshot states."""

    def __init__(self, db: Session):
        """Initialize the comparison service."""
        self.db = db
        self.snapshot_repo = SnapshotRepository(db)

    def compare_snapshots_by_dataset(
        self, pool: str, dataset: str, system_ids: List[UUID]
    ) -> Dict[str, Any]:
        """
        Compare snapshots for a specific dataset across multiple systems.

        Returns:
            Dictionary with comparison results including:
            - common_snapshots: List of snapshot names present on all systems
            - unique_snapshots: Dict mapping system_id to unique snapshot names
            - missing_snapshots: Dict mapping system_id to missing snapshot names
            - latest_snapshots: Dict mapping system_id to latest snapshot info
        """
        logger.info(f"Comparing snapshots for {pool}/{dataset} across {len(system_ids)} systems")

        # Get snapshots for each system
        system_snapshots: Dict[UUID, List[SnapshotModel]] = {}
        for system_id in system_ids:
            snapshots = self.snapshot_repo.get_by_pool_dataset(
                pool=pool, dataset=dataset, system_id=system_id
            )
            system_snapshots[system_id] = snapshots

        # Extract snapshot names (normalize by removing pool/dataset prefix)
        system_snapshot_names: Dict[UUID, Set[str]] = {}
        for system_id, snapshots in system_snapshots.items():
            names = {self._extract_snapshot_name(snapshot.name) for snapshot in snapshots}
            system_snapshot_names[system_id] = names

        # Find common snapshots (intersection of all sets)
        if not system_snapshot_names:
            return {
                "common_snapshots": [],
                "unique_snapshots": {},
                "missing_snapshots": {},
                "latest_snapshots": {},
            }

        common_snapshots = (
            set.intersection(*system_snapshot_names.values()) if system_snapshot_names else set()
        )

        # Find unique snapshots per system
        unique_snapshots: Dict[UUID, List[str]] = {}
        for system_id, names in system_snapshot_names.items():
            other_names = (
                set.union(
                    *[names for sid, names in system_snapshot_names.items() if sid != system_id]
                )
                if len(system_snapshot_names) > 1
                else set()
            )
            unique = names - other_names
            unique_snapshots[system_id] = sorted(list(unique))

        # Find missing snapshots per system
        missing_snapshots: Dict[UUID, List[str]] = {}
        all_snapshots = (
            set.union(*system_snapshot_names.values()) if system_snapshot_names else set()
        )
        for system_id, names in system_snapshot_names.items():
            missing = all_snapshots - names
            missing_snapshots[system_id] = sorted(list(missing))

        # Find latest snapshot per system
        latest_snapshots: Dict[UUID, Dict[str, Any]] = {}
        for system_id, snapshots in system_snapshots.items():
            if snapshots:
                latest = max(snapshots, key=lambda s: s.timestamp)
                latest_snapshots[system_id] = {
                    "name": latest.name,
                    "timestamp": latest.timestamp.isoformat(),
                    "size": latest.size,
                }

        return {
            "pool": pool,
            "dataset": dataset,
            "common_snapshots": sorted(list(common_snapshots)),
            "unique_snapshots": {str(sid): names for sid, names in unique_snapshots.items()},
            "missing_snapshots": {str(sid): names for sid, names in missing_snapshots.items()},
            "latest_snapshots": {str(sid): info for sid, info in latest_snapshots.items()},
            "comparison_timestamp": datetime.now(timezone.utc).isoformat(),
        }

    def find_snapshot_differences(
        self, system_id_1: UUID, system_id_2: UUID, pool: str, dataset: str
    ) -> Dict[str, Any]:
        """
        Find differences between snapshots on two systems for a specific dataset.

        Returns:
            Dictionary with differences including:
            - only_in_system_1: Snapshots only in first system
            - only_in_system_2: Snapshots only in second system
            - in_both: Snapshots in both systems
        """
        snapshots_1 = self.snapshot_repo.get_by_pool_dataset(
            pool=pool, dataset=dataset, system_id=system_id_1
        )
        snapshots_2 = self.snapshot_repo.get_by_pool_dataset(
            pool=pool, dataset=dataset, system_id=system_id_2
        )

        names_1 = {self._extract_snapshot_name(s.name) for s in snapshots_1}
        names_2 = {self._extract_snapshot_name(s.name) for s in snapshots_2}

        only_in_1 = sorted(list(names_1 - names_2))
        only_in_2 = sorted(list(names_2 - names_1))
        in_both = sorted(list(names_1 & names_2))

        return {
            "system_1": str(system_id_1),
            "system_2": str(system_id_2),
            "pool": pool,
            "dataset": dataset,
            "only_in_system_1": only_in_1,
            "only_in_system_2": only_in_2,
            "in_both": in_both,
            "comparison_timestamp": datetime.now(timezone.utc).isoformat(),
        }

    def get_snapshot_gaps(
        self, system_ids: List[UUID], pool: str, dataset: str
    ) -> List[Dict[str, Any]]:
        """
        Identify gaps in snapshot sequences across systems.

        Returns a list of gaps found, where a gap is a missing snapshot
        that exists on other systems but not on a particular system.
        """
        comparison = self.compare_snapshots_by_dataset(pool, dataset, system_ids)
        gaps = []

        # Build a map of snapshot_name -> list of system_ids that have it
        snapshot_to_systems: Dict[str, List[str]] = {}
        all_system_ids_str = [str(sid) for sid in system_ids]

        # Common snapshots are present on all systems
        common_snapshots = comparison.get("common_snapshots", [])
        for snapshot_name in common_snapshots:
            snapshot_to_systems[snapshot_name] = all_system_ids_str.copy()

        # Unique snapshots are only on specific systems
        unique_snapshots = comparison.get("unique_snapshots", {})
        for system_id_str, names in unique_snapshots.items():
            for snapshot_name in names:
                if snapshot_name not in snapshot_to_systems:
                    snapshot_to_systems[snapshot_name] = []
                if system_id_str not in snapshot_to_systems[snapshot_name]:
                    snapshot_to_systems[snapshot_name].append(system_id_str)

        for system_id_str, missing_names in comparison["missing_snapshots"].items():
            for snapshot_name in missing_names:
                # Find which systems have this snapshot from our map
                systems_with_snapshot = snapshot_to_systems.get(snapshot_name, [])
                # Filter out the current system
                systems_with_snapshot = [
                    sid for sid in systems_with_snapshot if sid != system_id_str
                ]

                gaps.append(
                    {
                        "system_id": system_id_str,
                        "missing_snapshot": snapshot_name,
                        "available_on_systems": systems_with_snapshot,
                        "pool": pool,
                        "dataset": dataset,
                    }
                )

        return gaps

    @staticmethod
    def _extract_snapshot_name(full_name: str) -> str:
        """
        Extract snapshot name from full ZFS snapshot path.

        Example: "tank/data@snapshot-20240115" -> "snapshot-20240115"
        """
        if "@" in full_name:
            return full_name.split("@")[-1]
        return full_name
