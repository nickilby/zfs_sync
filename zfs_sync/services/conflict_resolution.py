"""Service for detecting and resolving snapshot conflicts."""

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional
from uuid import UUID

from sqlalchemy.orm import Session

from zfs_sync.database.models import SnapshotModel
from zfs_sync.database.repositories import (
    SnapshotRepository,
    SyncGroupRepository,
    SyncStateRepository,
)
from zfs_sync.logging_config import get_logger
from zfs_sync.models import SyncStatus
from zfs_sync.services.snapshot_comparison import SnapshotComparisonService

logger = get_logger(__name__)


class ConflictType(str, Enum):
    """Types of conflicts that can occur."""

    DIVERGENT_SNAPSHOTS = "divergent_snapshots"  # Different snapshots with same name
    MISSING_BASE = "missing_base"  # Missing base snapshot for incremental sync
    TIMESTAMP_MISMATCH = "timestamp_mismatch"  # Same name but different timestamps
    SIZE_MISMATCH = "size_mismatch"  # Same name but different sizes
    ORPHANED_SNAPSHOT = "orphaned_snapshot"  # Snapshot exists but no common ancestor


class ConflictResolutionStrategy(str, Enum):
    """Available conflict resolution strategies."""

    AUTO_RESOLVE = "auto_resolve"  # Automatically resolve using strategy
    MANUAL = "manual"  # Require manual intervention
    IGNORE = "ignore"  # Ignore the conflict
    USE_NEWEST = "use_newest"  # Use the newest snapshot
    USE_LARGEST = "use_largest"  # Use the largest snapshot
    USE_MAJORITY = "use_majority"  # Use snapshot present on most systems


class ConflictResolutionService:
    """Service for detecting and resolving snapshot conflicts."""

    def __init__(self, db: Session):
        """Initialize the conflict resolution service."""
        self.db = db
        self.snapshot_repo = SnapshotRepository(db)
        self.sync_group_repo = SyncGroupRepository(db)
        self.sync_state_repo = SyncStateRepository(db)
        self.comparison_service = SnapshotComparisonService(db)

    def detect_conflicts(
        self, sync_group_id: UUID, pool: str, dataset: str
    ) -> List[Dict[str, Any]]:
        """
        Detect conflicts for a specific dataset in a sync group.

        Returns a list of detected conflicts with details.
        """
        logger.info(f"Detecting conflicts for {pool}/{dataset} in sync group {sync_group_id}")

        sync_group = self.sync_group_repo.get(sync_group_id)
        if not sync_group:
            raise ValueError(
                f"Sync group '{sync_group_id}' not found. "
                f"Cannot detect conflicts for non-existent sync group."
            )

        system_ids = [assoc.system_id for assoc in sync_group.system_associations]

        if len(system_ids) < 2:
            return []  # No conflicts possible with less than 2 systems

        conflicts = []

        # Get all snapshots for this dataset across systems
        all_snapshots: Dict[UUID, List[SnapshotModel]] = {}
        for system_id in system_ids:
            snapshots = self.snapshot_repo.get_by_pool_dataset(
                pool=pool, dataset=dataset, system_id=system_id
            )
            all_snapshots[system_id] = snapshots

        # Extract snapshot names (normalized)
        snapshot_names_by_system: Dict[UUID, Dict[str, SnapshotModel]] = {}
        for system_id, snapshots in all_snapshots.items():
            names_dict = {}
            for snapshot in snapshots:
                name = self.comparison_service.extract_snapshot_name(snapshot.name)
                names_dict[name] = snapshot
            snapshot_names_by_system[system_id] = names_dict

        # Find all unique snapshot names
        all_names = set()
        for names_dict in snapshot_names_by_system.values():
            all_names.update(names_dict.keys())

        # Check for conflicts
        for snapshot_name in all_names:
            # Find which systems have this snapshot
            systems_with_snapshot = [
                sid
                for sid, names_dict in snapshot_names_by_system.items()
                if snapshot_name in names_dict
            ]

            if len(systems_with_snapshot) == 0:
                continue

            # Get snapshot details from each system
            snapshots_by_system = {
                sid: snapshot_names_by_system[sid][snapshot_name] for sid in systems_with_snapshot
            }

            # Check for timestamp mismatches
            timestamps = {sid: snap.timestamp for sid, snap in snapshots_by_system.items()}
            unique_timestamps = set(timestamps.values())
            if len(unique_timestamps) > 1:
                conflicts.append(
                    {
                        "type": ConflictType.TIMESTAMP_MISMATCH.value,
                        "snapshot_name": snapshot_name,
                        "pool": pool,
                        "dataset": dataset,
                        "sync_group_id": str(sync_group_id),
                        "systems": {
                            str(sid): {
                                "timestamp": snap.timestamp.isoformat(),
                                "size": snap.size,
                                "snapshot_id": str(snap.id),
                            }
                            for sid, snap in snapshots_by_system.items()
                        },
                        "severity": "medium",
                        "detected_at": datetime.now(timezone.utc).isoformat(),
                    }
                )

            # Check for size mismatches
            sizes = {sid: snap.size for sid, snap in snapshots_by_system.items() if snap.size}
            if len(sizes) > 1:
                unique_sizes = set(sizes.values())
                if len(unique_sizes) > 1:
                    conflicts.append(
                        {
                            "type": ConflictType.SIZE_MISMATCH.value,
                            "snapshot_name": snapshot_name,
                            "pool": pool,
                            "dataset": dataset,
                            "sync_group_id": str(sync_group_id),
                            "systems": {
                                str(sid): {
                                    "timestamp": snap.timestamp.isoformat(),
                                    "size": snap.size,
                                    "snapshot_id": str(snap.id),
                                }
                                for sid, snap in snapshots_by_system.items()
                            },
                            "severity": "low",
                            "detected_at": datetime.now(timezone.utc).isoformat(),
                        }
                    )

            # Check for divergent snapshots (same name, different content)
            # This is detected when we have the same snapshot name but different
            # snapshot IDs across systems
            snapshot_ids = {str(snap.id) for snap in snapshots_by_system.values()}
            if len(snapshot_ids) > 1:
                conflicts.append(
                    {
                        "type": ConflictType.DIVERGENT_SNAPSHOTS.value,
                        "snapshot_name": snapshot_name,
                        "pool": pool,
                        "dataset": dataset,
                        "sync_group_id": str(sync_group_id),
                        "systems": {
                            str(sid): {
                                "timestamp": snap.timestamp.isoformat(),
                                "size": snap.size,
                                "snapshot_id": str(snap.id),
                            }
                            for sid, snap in snapshots_by_system.items()
                        },
                        "severity": "high",
                        "detected_at": datetime.now(timezone.utc).isoformat(),
                    }
                )

        # Check for missing base snapshots (orphaned snapshots)
        for system_id, snapshots in all_snapshots.items():
            for snapshot in snapshots:
                snapshot_name = self.comparison_service.extract_snapshot_name(snapshot.name)
                # Check if this snapshot exists on other systems
                other_systems_have = any(
                    snapshot_name in snapshot_names_by_system.get(other_id, {})
                    for other_id in system_ids
                    if other_id != system_id
                )

                if not other_systems_have:
                    # Check if there's a common ancestor
                    has_ancestor = self._has_common_ancestor(
                        snapshot, all_snapshots, system_ids, system_id
                    )

                    if not has_ancestor:
                        conflicts.append(
                            {
                                "type": ConflictType.ORPHANED_SNAPSHOT.value,
                                "snapshot_name": snapshot_name,
                                "pool": pool,
                                "dataset": dataset,
                                "sync_group_id": str(sync_group_id),
                                "systems": {
                                    str(system_id): {
                                        "timestamp": snapshot.timestamp.isoformat(),
                                        "size": snapshot.size,
                                        "snapshot_id": str(snapshot.id),
                                    }
                                },
                                "severity": "medium",
                                "detected_at": datetime.now(timezone.utc).isoformat(),
                            }
                        )

        return conflicts

    def resolve_conflict(
        self,
        conflict: Dict[str, Any],
        strategy: ConflictResolutionStrategy,
        resolution_data: Optional[Dict] = None,
    ) -> Dict[str, Any]:
        """
        Resolve a conflict using the specified strategy.

        Args:
            conflict: The conflict to resolve
            strategy: Resolution strategy to use
            resolution_data: Additional data for resolution (e.g., chosen system_id)

        Returns:
            Resolution result with actions to take
        """
        logger.info(
            f"Resolving conflict {conflict.get('type')} for {conflict.get('snapshot_name')} "
            f"using strategy {strategy.value}"
        )

        if strategy == ConflictResolutionStrategy.MANUAL:
            return {
                "status": "requires_manual_intervention",
                "conflict": conflict,
                "message": "This conflict requires manual resolution",
            }

        if strategy == ConflictResolutionStrategy.IGNORE:
            return {
                "status": "ignored",
                "conflict": conflict,
                "message": "Conflict will be ignored",
            }

        # Auto-resolve strategies
        systems = conflict.get("systems", {})
        if not systems:
            return {
                "status": "error",
                "message": "No systems found in conflict",
            }

        if strategy == ConflictResolutionStrategy.USE_NEWEST:
            # Find system with newest timestamp
            # Parse ISO timestamp strings to datetime objects for proper comparison
            def get_timestamp(system_data: Dict[str, Any]) -> datetime:
                timestamp_str = system_data.get("timestamp", "")
                if isinstance(timestamp_str, str):
                    try:
                        return datetime.fromisoformat(timestamp_str.replace("Z", "+00:00"))
                    except (ValueError, AttributeError):
                        # Fallback to epoch if parsing fails
                        return datetime.min.replace(tzinfo=timezone.utc)
                return datetime.min.replace(tzinfo=timezone.utc)

            newest_system = max(
                systems.items(),
                key=lambda x: get_timestamp(x[1]),
            )
            return self._create_resolution_action(conflict, newest_system[0], "use_newest")

        if strategy == ConflictResolutionStrategy.USE_LARGEST:
            # Find system with largest size
            largest_system = max(
                systems.items(),
                key=lambda x: x[1].get("size", 0) or 0,
            )
            return self._create_resolution_action(conflict, largest_system[0], "use_largest")

        if strategy == ConflictResolutionStrategy.USE_MAJORITY:
            # Use the snapshot that appears on most systems
            # For now, use the first system (would need more complex logic for true majority)
            first_system = list(systems.keys())[0]
            return self._create_resolution_action(conflict, first_system, "use_majority")

        if strategy == ConflictResolutionStrategy.AUTO_RESOLVE:
            # Default auto-resolve: use newest
            return self.resolve_conflict(conflict, ConflictResolutionStrategy.USE_NEWEST)

        return {
            "status": "error",
            "message": f"Unknown strategy: {strategy}",
        }

    def _create_resolution_action(
        self, conflict: Dict, source_system_id: str, reason: str
    ) -> Dict[str, Any]:
        """Create a resolution action dictionary."""
        systems = conflict.get("systems", {})
        source_info = systems.get(source_system_id, {})

        # Determine target systems (all except source)
        target_systems = [sid for sid in systems.keys() if sid != source_system_id]

        return {
            "status": "resolved",
            "strategy": reason,
            "conflict": conflict,
            "actions": [
                {
                    "action_type": "sync_snapshot",
                    "source_system_id": source_system_id,
                    "target_system_id": target_id,
                    "snapshot_id": source_info.get("snapshot_id"),
                    "snapshot_name": conflict.get("snapshot_name"),
                    "pool": conflict.get("pool"),
                    "dataset": conflict.get("dataset"),
                    "reason": f"Resolving conflict using {reason}",
                }
                for target_id in target_systems
            ],
            "resolution_timestamp": datetime.now(timezone.utc).isoformat(),
        }

    def _has_common_ancestor(
        self,
        snapshot: SnapshotModel,
        all_snapshots: Dict[UUID, List[SnapshotModel]],
        system_ids: List[UUID],
        current_system_id: UUID,
    ) -> bool:
        """Check if a snapshot has a common ancestor on other systems."""
        # Simplified: check if there's an older snapshot with same name pattern
        # In a real implementation, this would check ZFS snapshot relationships
        snapshot_name = self.comparison_service.extract_snapshot_name(snapshot.name)

        for other_system_id in system_ids:
            if other_system_id == current_system_id:
                continue

            other_snapshots = all_snapshots.get(other_system_id, [])
            for other_snap in other_snapshots:
                other_name = self.comparison_service.extract_snapshot_name(other_snap.name)
                # Check if there's a snapshot with similar name pattern (simplified check)
                if other_name.startswith(
                    snapshot_name.split("-")[0] if "-" in snapshot_name else snapshot_name
                ):
                    if other_snap.timestamp < snapshot.timestamp:
                        return True

        return False

    def get_all_conflicts(self, sync_group_id: UUID) -> List[Dict[str, Any]]:
        """Get all conflicts for a sync group across all datasets."""
        sync_group = self.sync_group_repo.get(sync_group_id)
        if not sync_group:
            raise ValueError(
                f"Sync group '{sync_group_id}' not found. "
                f"Cannot detect conflicts for non-existent sync group."
            )

        # Get all unique datasets from snapshots in this sync group
        system_ids = [assoc.system_id for assoc in sync_group.system_associations]
        datasets = set()

        for system_id in system_ids:
            snapshots = self.snapshot_repo.get_by_system(system_id)
            for snapshot in snapshots:
                datasets.add((snapshot.pool, snapshot.dataset))

        all_conflicts = []
        for pool, dataset in datasets:
            conflicts = self.detect_conflicts(sync_group_id, pool, dataset)
            all_conflicts.extend(conflicts)

        return all_conflicts

    def mark_conflict_resolved(
        self,
        conflict_id: str,
        resolution: Dict[str, Any],
        resolved_by: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Mark a conflict as resolved and update sync states.

        This is called after manual or automatic resolution.
        """
        logger.info(f"Marking conflict {conflict_id} as resolved")

        conflict = resolution.get("conflict", {})
        actions = resolution.get("actions", [])

        # Update sync states for affected systems
        from zfs_sync.services.sync_coordination import SyncCoordinationService

        sync_service = SyncCoordinationService(self.db)

        # Mark all systems involved in the conflict
        systems_involved = conflict.get("systems", {})
        sync_group_id = UUID(conflict.get("sync_group_id"))
        dataset = conflict.get("dataset")

        for system_id_str in systems_involved.keys():
            system_id = UUID(system_id_str)

            # Update sync state to reflect conflict resolution
            if actions:
                # If there are actions, mark target systems as syncing
                target_system_ids = [UUID(action["target_system_id"]) for action in actions]
                if system_id in target_system_ids:
                    sync_service.update_sync_state(
                        sync_group_id=sync_group_id,
                        dataset=dataset,
                        system_id=system_id,
                        status=SyncStatus.SYNCING,  # Will be updated to IN_SYNC after actual sync
                    )
            else:
                # If no actions, mark as resolved (conflict acknowledged)
                sync_service.update_sync_state(
                    sync_group_id=sync_group_id,
                    dataset=dataset,
                    system_id=system_id,
                    status=SyncStatus.OUT_OF_SYNC,  # Reset to out_of_sync for re-evaluation
                )

        return {
            "conflict_id": conflict_id,
            "status": "resolved",
            "resolved_at": datetime.now(timezone.utc).isoformat(),
            "resolved_by": resolved_by or "system",
            "resolution": resolution,
        }

    def mark_conflicts_in_sync_states(
        self, sync_group_id: UUID, conflicts: List[Dict[str, Any]]
    ) -> None:
        """
        Mark sync states as having conflicts when conflicts are detected.

        This updates the sync state status to CONFLICT for affected snapshots.
        """
        from zfs_sync.services.sync_coordination import SyncCoordinationService

        sync_service = SyncCoordinationService(self.db)

        for conflict in conflicts:
            systems = conflict.get("systems", {})
            dataset = conflict.get("dataset")
            sync_group_id = UUID(conflict.get("sync_group_id"))

            for system_id_str in systems.keys():
                system_id = UUID(system_id_str)

                sync_service.update_sync_state(
                    sync_group_id=sync_group_id,
                    dataset=dataset,
                    system_id=system_id,
                    status=SyncStatus.CONFLICT,
                    error_message=f"Conflict detected: {conflict.get('type')}",
                )
