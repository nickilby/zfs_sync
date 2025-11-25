"""Service for coordinating snapshot synchronization across systems."""

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple
from uuid import UUID

from sqlalchemy.orm import Session

from zfs_sync.database.models import SyncStateModel
from zfs_sync.database.repositories import (
    SnapshotRepository,
    SyncGroupRepository,
    SyncStateRepository,
    SystemRepository,
)
from zfs_sync.logging_config import get_logger
from zfs_sync.models import SyncStatus
from zfs_sync.services.snapshot_comparison import SnapshotComparisonService

logger = get_logger(__name__)


class SyncCoordinationService:
    """Service for coordinating snapshot synchronization."""

    def __init__(self, db: Session):
        """Initialize the sync coordination service."""
        self.db = db
        self.sync_group_repo = SyncGroupRepository(db)
        self.sync_state_repo = SyncStateRepository(db)
        self.snapshot_repo = SnapshotRepository(db)
        self.system_repo = SystemRepository(db)
        self.comparison_service = SnapshotComparisonService(db)

    def detect_sync_mismatches(self, sync_group_id: UUID) -> List[Dict[str, Any]]:
        """
        Detect snapshot mismatches for a sync group.

        Returns a list of mismatches that need to be synchronized.
        Note: This detects missing snapshots, not conflicts. Use ConflictResolutionService
        to detect conflicts.
        """
        logger.info(f"Detecting sync mismatches for sync group {sync_group_id}")

        sync_group = self.sync_group_repo.get(sync_group_id)
        if not sync_group:
            raise ValueError(
                f"Sync group '{sync_group_id}' not found. "
                f"Cannot detect sync mismatches for non-existent sync group."
            )

        if not sync_group.enabled:
            logger.info(f"Sync group {sync_group_id} is disabled")
            return []

        # Get all systems in the sync group
        system_ids = [assoc.system_id for assoc in sync_group.system_associations]

        if len(system_ids) < 2:
            logger.warning(f"Sync group {sync_group_id} has less than 2 systems")
            return []

        # Get all datasets that should be synced (from existing snapshots)
        datasets = self._get_datasets_for_systems(system_ids)

        mismatches = []
        for pool, dataset in datasets:
            comparison = self.comparison_service.compare_snapshots_by_dataset(
                pool=pool, dataset=dataset, system_ids=system_ids
            )

            # Find systems with missing snapshots
            for system_id_str, missing_snapshots in comparison["missing_snapshots"].items():
                if missing_snapshots:
                    system_id = UUID(system_id_str)
                    for missing_snapshot in missing_snapshots:
                        # Find which systems have this snapshot
                        source_systems = self._find_systems_with_snapshot(
                            pool, dataset, missing_snapshot, system_ids
                        )

                        if source_systems:
                            mismatches.append(
                                {
                                    "sync_group_id": str(sync_group_id),
                                    "pool": pool,
                                    "dataset": dataset,
                                    "target_system_id": str(system_id),
                                    "missing_snapshot": missing_snapshot,
                                    "source_system_ids": [str(sid) for sid in source_systems],
                                    "priority": self._calculate_priority(missing_snapshot, comparison),
                                }
                            )

        return mismatches

    def determine_sync_actions(
        self, sync_group_id: UUID, system_id: Optional[UUID] = None
    ) -> List[Dict[str, Any]]:
        """
        Determine sync actions needed for a sync group or specific system.

        Returns a list of actions that should be performed.
        """
        logger.info(f"Determining sync actions for sync group {sync_group_id}")

        mismatches = self.detect_sync_mismatches(sync_group_id)

        if system_id:
            # Filter to actions for specific system
            mismatches = [m for m in mismatches if UUID(m["target_system_id"]) == system_id]

        actions = []
        for mismatch in mismatches:
            source_system_id = UUID(mismatch["source_system_ids"][0])  # Use first available
            
            # Find snapshot_id from source system
            snapshot_id = self._find_snapshot_id(
                pool=mismatch["pool"],
                dataset=mismatch["dataset"],
                snapshot_name=mismatch["missing_snapshot"],
                system_id=source_system_id,
            )
            
            action = {
                "action_type": "sync_snapshot",
                "sync_group_id": mismatch["sync_group_id"],
                "pool": mismatch["pool"],
                "dataset": mismatch["dataset"],
                "target_system_id": mismatch["target_system_id"],
                "source_system_id": mismatch["source_system_ids"][0],  # Use first available
                "snapshot_name": mismatch["missing_snapshot"],
                "snapshot_id": str(snapshot_id) if snapshot_id else None,
                "priority": mismatch["priority"],
                "estimated_size": self._estimate_snapshot_size(
                    mismatch["pool"],
                    mismatch["dataset"],
                    mismatch["missing_snapshot"],
                    source_system_id,
                ),
            }
            actions.append(action)

        # Sort by priority (higher priority first)
        actions.sort(key=lambda x: x["priority"], reverse=True)

        return actions

    def get_sync_instructions(
        self, system_id: UUID, sync_group_id: Optional[UUID] = None
    ) -> Dict[str, Any]:
        """
        Get sync instructions for a system.

        Returns instructions for what snapshots need to be synced.
        """
        logger.info(f"Getting sync instructions for system {system_id}")

        # Get all sync groups this system belongs to
        if sync_group_id:
            sync_groups = [self.sync_group_repo.get(sync_group_id)]
        else:
            # Find all sync groups containing this system
            all_groups = self.sync_group_repo.get_all()
            sync_groups = [
                group
                for group in all_groups
                if any(assoc.system_id == system_id for assoc in group.system_associations)
                and group.enabled
            ]

        all_actions = []
        for group in sync_groups:
            if group:
                actions = self.determine_sync_actions(group.id, system_id=system_id)
                all_actions.extend(actions)

        return {
            "system_id": str(system_id),
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "actions": all_actions,
            "action_count": len(all_actions),
            "sync_groups": [str(g.id) for g in sync_groups if g],
        }

    def update_sync_state(
        self,
        sync_group_id: UUID,
        snapshot_id: UUID,
        system_id: UUID,
        status: SyncStatus,
        error_message: Optional[str] = None,
    ) -> SyncStateModel:
        """
        Update or create a sync state record.

        Returns the updated or created sync state.
        """
        # Check if sync state already exists
        existing_states = self.sync_state_repo.get_by_sync_group(sync_group_id)
        existing = next(
            (
                s
                for s in existing_states
                if s.snapshot_id == snapshot_id and s.system_id == system_id
            ),
            None,
        )

        if existing:
            # Update existing
            existing.status = status.value
            existing.last_check = datetime.now(timezone.utc)
            if status == SyncStatus.IN_SYNC:
                existing.last_sync = datetime.now(timezone.utc)
            if error_message:
                existing.error_message = error_message
            else:
                existing.error_message = None
            self.db.commit()
            self.db.refresh(existing)
            return existing
        else:
            # Create new
            return self.sync_state_repo.create(
                sync_group_id=sync_group_id,
                snapshot_id=snapshot_id,
                system_id=system_id,
                status=status.value,
                last_check=datetime.now(timezone.utc),
                error_message=error_message,
            )

    def get_sync_status_summary(self, sync_group_id: UUID) -> Dict[str, Any]:
        """
        Get a summary of sync status for a sync group.

        Returns statistics about sync states.
        """
        sync_states = self.sync_state_repo.get_by_sync_group(sync_group_id)

        status_counts = {}
        for state in sync_states:
            status = state.status
            status_counts[status] = status_counts.get(status, 0) + 1

        return {
            "sync_group_id": str(sync_group_id),
            "total_states": len(sync_states),
            "status_breakdown": status_counts,
            "in_sync_count": status_counts.get("in_sync", 0),
            "out_of_sync_count": status_counts.get("out_of_sync", 0),
            "syncing_count": status_counts.get("syncing", 0),
            "conflict_count": status_counts.get("conflict", 0),
            "error_count": status_counts.get("error", 0),
            "last_updated": max(
                (s.last_check for s in sync_states if s.last_check), default=None
            ),
        }

    def _get_datasets_for_systems(self, system_ids: List[UUID]) -> List[Tuple[str, str]]:
        """Get unique pool/dataset combinations from snapshots for given systems."""
        datasets = set()
        for system_id in system_ids:
            snapshots = self.snapshot_repo.get_by_system(system_id)
            for snapshot in snapshots:
                datasets.add((snapshot.pool, snapshot.dataset))
        return list(datasets)

    def _find_systems_with_snapshot(
        self, pool: str, dataset: str, snapshot_name: str, system_ids: List[UUID]
    ) -> List[UUID]:
        """Find which systems have a specific snapshot."""
        systems_with_snapshot = []
        for system_id in system_ids:
            snapshots = self.snapshot_repo.get_by_pool_dataset(
                pool=pool, dataset=dataset, system_id=system_id
            )
            for snapshot in snapshots:
                if self.comparison_service._extract_snapshot_name(snapshot.name) == snapshot_name:
                    systems_with_snapshot.append(system_id)
                    break
        return systems_with_snapshot

    def _calculate_priority(self, snapshot_name: str, comparison: Dict) -> int:
        """
        Calculate priority for syncing a snapshot.

        Higher priority = more important to sync.
        """
        priority = 10  # Base priority

        # If it's the latest snapshot, increase priority
        latest_snapshots = comparison.get("latest_snapshots", {})
        for system_id_str, latest_info in latest_snapshots.items():
            # Extract snapshot name from full name (e.g., "tank/data@snapshot-20240115" -> "snapshot-20240115")
            latest_snapshot_name = self.comparison_service._extract_snapshot_name(latest_info.get("name", ""))
            if latest_snapshot_name == snapshot_name:
                priority += 20
                break

        # If many systems are missing it, increase priority
        missing_count = sum(
            1
            for missing_list in comparison.get("missing_snapshots", {}).values()
            if snapshot_name in missing_list
        )
        priority += missing_count * 5

        return priority

    def _find_snapshot_id(
        self, pool: str, dataset: str, snapshot_name: str, system_id: UUID
    ) -> Optional[UUID]:
        """
        Find snapshot_id for a given snapshot name on a system.
        
        Returns the snapshot ID if found, None otherwise.
        """
        snapshots = self.snapshot_repo.get_by_pool_dataset(
            pool=pool, dataset=dataset, system_id=system_id
        )
        for snapshot in snapshots:
            if self.comparison_service._extract_snapshot_name(snapshot.name) == snapshot_name:
                return snapshot.id
        logger.warning(
            f"Could not find snapshot_id for {snapshot_name} on system {system_id} "
            f"for {pool}/{dataset}"
        )
        return None

    def _estimate_snapshot_size(
        self, pool: str, dataset: str, snapshot_name: str, source_system_id: UUID
    ) -> Optional[int]:
        """Estimate the size of a snapshot for transfer planning."""
        snapshots = self.snapshot_repo.get_by_pool_dataset(
            pool=pool, dataset=dataset, system_id=source_system_id
        )
        for snapshot in snapshots:
            if self.comparison_service._extract_snapshot_name(snapshot.name) == snapshot_name:
                return snapshot.size
        return None

