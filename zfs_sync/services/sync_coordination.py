"""Service for coordinating snapshot synchronization across systems."""

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set, Tuple
from uuid import UUID

from sqlalchemy.orm import Session

from zfs_sync.database.models import SyncStateModel
from zfs_sync.config import get_settings
from zfs_sync.database.repositories import (
    SnapshotRepository,
    SyncGroupRepository,
    SyncStateRepository,
    SystemRepository,
)
from zfs_sync.logging_config import get_logger
from zfs_sync.models import SyncStatus
from zfs_sync.services.snapshot_comparison import SnapshotComparisonService
from zfs_sync.services.ssh_command_generator import SSHCommandGenerator
from zfs_sync.services.sync_validators import (
    is_midnight_snapshot,
    validate_snapshot_gap,
)

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
        self.diagnostics: List[Dict[str, Any]] = []
        self.settings = get_settings()

    def detect_sync_mismatches(self, sync_group_id: UUID) -> List[Dict[str, Any]]:
        """
        Detect if target systems are behind hub system for any datasets.

        Only evaluates latest midnight snapshot per dataset.
        Returns mismatches only for hub → target direction.
        """
        sync_group = self.sync_group_repo.get(sync_group_id)
        if not sync_group:
            raise ValueError(
                f"Sync group '{sync_group_id}' not found. "
                f"Cannot detect sync mismatches for non-existent sync group."
            )

        if not sync_group.enabled:
            logger.info("Sync group %s is disabled", sync_group_id)
            return []

        # Verify this is a directional sync group with a hub
        if not sync_group.directional or not sync_group.hub_system_id:
            logger.warning(
                "Sync group %s is not configured for directional sync with hub. "
                "Only directional hub→target sync is supported.",
                sync_group_id,
            )
            return []

        # Get all systems in the sync group
        all_system_ids = [assoc.system_id for assoc in sync_group.system_associations]
        hub_system_id = sync_group.hub_system_id

        if hub_system_id not in all_system_ids:
            logger.warning(
                "Hub system %s not in sync group %s",
                hub_system_id,
                sync_group_id,
            )
            return []

        if len(all_system_ids) < 2:
            logger.warning("Sync group %s has less than 2 systems", sync_group_id)
            return []

        # Get target systems (all systems except hub)
        target_system_ids = [sid for sid in all_system_ids if sid != hub_system_id]

        # Get hub and target system info for logging
        hub_system = self.system_repo.get(hub_system_id)
        hub_hostname = hub_system.hostname if hub_system else str(hub_system_id)

        logger.info(
            "Evaluating sync group '%s' (hub: %s, targets: %s)",
            sync_group.name if sync_group.name else str(sync_group_id),
            hub_hostname,
            [
                self.system_repo.get(sid).hostname if self.system_repo.get(sid) else str(sid)
                for sid in target_system_ids
            ],
        )

        # Get all datasets that should be synced (from all systems in group)
        datasets = self._get_datasets_for_systems(all_system_ids)
        logger.info("Found %d datasets to evaluate", len(datasets))

        mismatches = []

        for dataset in datasets:
            # Get all snapshots for hub and targets for this dataset
            hub_snapshots = self.snapshot_repo.get_by_dataset(
                dataset=dataset, system_id=hub_system_id
            )

            # Find latest midnight snapshot from hub
            hub_midnight_snapshots = [
                s
                for s in hub_snapshots
                if is_midnight_snapshot(self.comparison_service.extract_snapshot_name(s.name))
            ]

            if not hub_midnight_snapshots:
                logger.debug(
                    "Dataset %s: Hub (%s) has no midnight snapshots, skipping",
                    dataset,
                    hub_hostname,
                )
                continue

            hub_latest = max(hub_midnight_snapshots, key=lambda s: s.timestamp)
            hub_latest_name = self.comparison_service.extract_snapshot_name(hub_latest.name)
            hub_latest_timestamp = hub_latest.timestamp

            # Check each target system
            for target_system_id in target_system_ids:
                target_system = self.system_repo.get(target_system_id)
                target_hostname = target_system.hostname if target_system else str(target_system_id)

                target_snapshots = self.snapshot_repo.get_by_dataset(
                    dataset=dataset, system_id=target_system_id
                )

                # Find latest midnight snapshot from target
                target_midnight_snapshots = [
                    s
                    for s in target_snapshots
                    if is_midnight_snapshot(self.comparison_service.extract_snapshot_name(s.name))
                ]

                if not target_midnight_snapshots:
                    # Target has no midnight snapshots - it's behind
                    logger.info(
                        "Dataset %s: Hub (%s) latest: %s, Target (%s) latest: (none) - OUT OF SYNC (target has no snapshots)",
                        dataset,
                        hub_hostname,
                        hub_latest_name,
                        target_hostname,
                    )
                    mismatch = {
                        "sync_group_id": str(sync_group_id),
                        "dataset": dataset,
                        "target_system_id": str(target_system_id),
                        "missing_snapshot": hub_latest_name,
                        "source_system_ids": [str(hub_system_id)],
                        "hub_latest_snapshot": hub_latest_name,
                        "hub_latest_timestamp": hub_latest_timestamp,
                        "target_latest_snapshot": None,
                        "target_latest_timestamp": None,
                    }
                    mismatches.append(mismatch)
                    continue

                target_latest = max(target_midnight_snapshots, key=lambda s: s.timestamp)
                target_latest_name = self.comparison_service.extract_snapshot_name(
                    target_latest.name
                )
                target_latest_timestamp = target_latest.timestamp

                # Check if target has hub's latest snapshot
                if target_latest_name == hub_latest_name:
                    # Target has hub's latest - in sync
                    logger.info(
                        "Dataset %s: Hub (%s) latest: %s, Target (%s) latest: %s - IN SYNC",
                        dataset,
                        hub_hostname,
                        hub_latest_name,
                        target_hostname,
                        target_latest_name,
                    )
                    continue

                # Target doesn't have hub's latest - check if it's behind
                if target_latest_timestamp < hub_latest_timestamp:
                    # Calculate time difference
                    time_diff = hub_latest_timestamp - target_latest_timestamp
                    hours_behind = time_diff.total_seconds() / 3600
                    days_behind = hours_behind / 24

                    logger.info(
                        "Dataset %s: Hub (%s) latest: %s, Target (%s) latest: %s - OUT OF SYNC (%.1f days behind)",
                        dataset,
                        hub_hostname,
                        hub_latest_name,
                        target_hostname,
                        target_latest_name,
                        days_behind,
                    )

                    mismatch = {
                        "sync_group_id": str(sync_group_id),
                        "dataset": dataset,
                        "target_system_id": str(target_system_id),
                        "missing_snapshot": hub_latest_name,
                        "source_system_ids": [str(hub_system_id)],
                        "hub_latest_snapshot": hub_latest_name,
                        "hub_latest_timestamp": hub_latest_timestamp,
                        "target_latest_snapshot": target_latest_name,
                        "target_latest_timestamp": target_latest_timestamp,
                    }
                    mismatches.append(mismatch)

        logger.info(
            "Detected %d mismatches for sync group %s (hub → targets)",
            len(mismatches),
            sync_group_id,
        )

        return mismatches

    def determine_sync_actions(
        self, sync_group_id: UUID, system_id: Optional[UUID] = None
    ) -> List[Dict[str, Any]]:
        """
        Generate sync actions for systems that are behind hub.

        Logic:
        1. Get mismatches (hub → target only)
        2. For each mismatch:
           a. Check if target is >72h behind hub's latest midnight snapshot
           b. If yes: Find incremental base (last common midnight snapshot)
           c. Generate sync command (incremental if base exists, full if not)
           d. Log human-readable message
        3. Return actions
        """
        mismatches = self.detect_sync_mismatches(sync_group_id)

        # Filter to specific system if requested
        if system_id:
            # For target systems, filter mismatches where system is the TARGET
            mismatches = [m for m in mismatches if UUID(m["target_system_id"]) == system_id]

        actions = []
        in_sync_count = 0
        out_of_sync_count = 0

        for mismatch in mismatches:
            hub_system_id = UUID(mismatch["source_system_ids"][0])
            target_system_id = UUID(mismatch["target_system_id"])
            dataset = mismatch["dataset"]
            hub_latest_snapshot = mismatch["hub_latest_snapshot"]
            hub_latest_timestamp = mismatch["hub_latest_timestamp"]
            target_latest_timestamp = mismatch.get("target_latest_timestamp")

            # Get system info for logging
            hub_system = self.system_repo.get(hub_system_id)
            target_system = self.system_repo.get(target_system_id)

            if not hub_system or not target_system:
                logger.warning(
                    "Skipping mismatch for dataset %s: hub or target system not found", dataset
                )
                continue

            hub_hostname = hub_system.hostname
            target_hostname = target_system.hostname

            # Check 72-hour window: target must be more than 72 hours behind hub
            if target_latest_timestamp:
                time_diff = hub_latest_timestamp - target_latest_timestamp
                hours_behind = time_diff.total_seconds() / 3600
            else:
                # Target has no snapshots - definitely out of sync
                hours_behind = float("inf")

            if hours_behind <= 72.0:
                # Within 72-hour window - systems are in sync
                in_sync_count += 1
                logger.info(
                    "Dataset %s: Target system '%s' is in sync with hub system '%s' "
                    "(within 72h window). Hub latest: %s, Target latest: %s",
                    dataset,
                    target_hostname,
                    hub_hostname,
                    hub_latest_snapshot,
                    mismatch.get("target_latest_snapshot", "none"),
                )
                continue

            # Out of sync by more than 72 hours - generate sync command
            out_of_sync_count += 1
            days_behind = hours_behind / 24

            logger.info(
                "Target system '%s' is behind hub system '%s' for dataset '%s' (%.1f days behind). "
                "Hub latest: %s, Target latest: %s. Creating sync instructions.",
                target_hostname,
                hub_hostname,
                dataset,
                days_behind,
                hub_latest_snapshot,
                mismatch.get("target_latest_snapshot", "none"),
            )

            # Find snapshot_id and pool from hub system
            snapshot_id, pool = self._find_snapshot_id_and_pool(
                dataset=dataset,
                snapshot_name=hub_latest_snapshot,
                system_id=hub_system_id,
            )

            if not pool:
                logger.warning(
                    "Could not determine pool for snapshot %s on hub system %s for dataset %s",
                    hub_latest_snapshot,
                    hub_hostname,
                    dataset,
                )
                continue

            # Find incremental base (last common midnight snapshot)
            incremental_base = self._find_incremental_base(
                dataset=dataset,
                target_system_id=target_system_id,
                source_system_id=hub_system_id,
            )
            is_incremental = incremental_base is not None

            # Get target pool
            target_pool = self._get_target_pool(dataset, target_system_id)
            if not target_pool:
                # Target has no snapshots yet - will need full send
                target_pool = pool  # Use hub's pool as fallback

            # Generate sync command
            sync_command = None
            if target_system.ssh_hostname:
                try:
                    if is_incremental and incremental_base:
                        sync_command = SSHCommandGenerator.generate_incremental_sync_command(
                            pool=pool,
                            dataset=dataset,
                            snapshot_name=hub_latest_snapshot,
                            incremental_base=incremental_base,
                            target_ssh_hostname=target_system.ssh_hostname,
                            target_pool=target_pool,
                            target_dataset=dataset,
                        )
                        logger.info("Creating incremental sync command: %s", sync_command)
                    else:
                        sync_command = SSHCommandGenerator.generate_full_sync_command(
                            pool=pool,
                            dataset=dataset,
                            snapshot_name=hub_latest_snapshot,
                            target_ssh_hostname=target_system.ssh_hostname,
                            target_pool=target_pool,
                            target_dataset=dataset,
                        )
                        logger.info("Creating full sync command: %s", sync_command)
                except (ValueError, TypeError, AttributeError) as e:
                    logger.warning("Failed to generate sync command for dataset %s: %s", dataset, e)
                    continue

            action = {
                "action_type": "sync_snapshot",
                "sync_group_id": mismatch["sync_group_id"],
                "pool": pool,
                "target_pool": target_pool,
                "dataset": dataset,
                "target_system_id": mismatch["target_system_id"],
                "source_system_id": str(hub_system_id),
                "snapshot_name": hub_latest_snapshot,
                "snapshot_id": str(snapshot_id) if snapshot_id else None,
                "priority": 10,  # Simple priority - can be enhanced later
                "estimated_size": self._estimate_snapshot_size(
                    dataset=dataset,
                    snapshot_name=hub_latest_snapshot,
                    source_system_id=hub_system_id,
                ),
                "source_ssh_hostname": hub_system.ssh_hostname,
                "source_ssh_user": hub_system.ssh_user,
                "source_ssh_port": hub_system.ssh_port,
                "target_ssh_hostname": target_system.ssh_hostname if target_system else None,
                "sync_command": sync_command,
                "incremental_base": incremental_base,
                "is_incremental": is_incremental,
            }
            actions.append(action)

        # Summary logging
        total_evaluated = in_sync_count + out_of_sync_count
        logger.info(
            "Summary: %d datasets evaluated, %d in sync (within 72h window), "
            "%d out of sync, %d sync commands generated",
            total_evaluated,
            in_sync_count,
            out_of_sync_count,
            len(actions),
        )

        return actions

    def get_sync_instructions(
        self,
        system_id: UUID,
        sync_group_id: Optional[UUID] = None,
        include_diagnostics: bool = False,
    ) -> Dict[str, Any]:
        """
        Get sync instructions for a system, grouped by dataset.
        """
        logger.info("Getting sync instructions for system %s", system_id)
        self.diagnostics = []  # Reset diagnostics

        # Get all sync groups this system belongs to
        if sync_group_id:
            sync_groups = [self.sync_group_repo.get(sync_group_id)]
            logger.debug("Filtering to sync group %s", sync_group_id)
        else:
            # Find all sync groups containing this system
            all_groups = self.sync_group_repo.get_all()
            sync_groups = [
                group
                for group in all_groups
                if any(assoc.system_id == system_id for assoc in group.system_associations)
                and group.enabled
            ]
            logger.debug("Found %d sync groups containing system %s", len(sync_groups), system_id)

        # Log sync group details
        for group in sync_groups:
            if group:
                logger.debug(
                    "Processing sync group %s (name=%s, directional=%s, hub_system_id=%s, enabled=%s)",
                    group.id,
                    group.name,
                    group.directional,
                    group.hub_system_id,
                    group.enabled,
                )
                system_ids_in_group = [assoc.system_id for assoc in group.system_associations]
                logger.debug(
                    "Sync group %s contains systems: %s",
                    group.id,
                    [str(sid) for sid in system_ids_in_group],
                )
                if group.directional and group.hub_system_id:
                    logger.debug(
                        "Directional sync: hub=%s, requesting instructions for=%s",
                        group.hub_system_id,
                        system_id,
                    )

        # Collect all actions for this system across sync groups
        all_actions: List[Dict[str, Any]] = []
        for group in sync_groups:
            if group:
                logger.debug(
                    "Determining sync actions for group %s, system %s", group.id, system_id
                )
                group_actions = self.determine_sync_actions(group.id, system_id=system_id)
                logger.debug(
                    "Found %d actions for system %s in group %s",
                    len(group_actions),
                    system_id,
                    group.id,
                )
                all_actions.extend(group_actions)

        logger.debug("Total actions collected: %d", len(all_actions))
        if len(all_actions) == 0:
            logger.warning(
                "No sync actions found for system %s. This may indicate a bug in mismatch detection.",
                system_id,
            )
            # Check if this is a hub system in directional sync
            is_hub = False
            for group in sync_groups:
                if group and group.directional and group.hub_system_id == system_id:
                    is_hub = True
                    break

            if is_hub:
                self.diagnostics.append(
                    {
                        "level": "info",
                        "message": (
                            f"No sync actions found for hub system {system_id}. "
                            "Hub should receive instructions on what snapshots to send to sources. "
                            "This may indicate no source systems are missing snapshots from the hub."
                        ),
                        "sync_groups_checked": len(sync_groups),
                    }
                )
            else:
                self.diagnostics.append(
                    {
                        "level": "warning",
                        "message": f"No sync actions found for system {system_id}",
                        "sync_groups_checked": len(sync_groups),
                    }
                )

        # Consolidate to one instruction per dataset using earliest incremental_base and latest snapshot
        consolidated: Dict[str, Dict[str, Any]] = {}
        for action in all_actions:
            dataset = action.get("dataset")
            if not dataset:
                continue
            entry = consolidated.get(dataset)
            snapshot_name = action.get("snapshot_name")
            incremental_base = (
                action.get("incremental_base") if action.get("is_incremental") else None
            )
            # Source pool is where the snapshot comes from (hub's pool when hub is source)
            source_pool = action.get("pool")
            # Target pool is where the snapshot goes to (receiving system's pool)
            target_pool = action.get("target_pool") or source_pool

            if entry is None:
                consolidated[dataset] = {
                    "pool": source_pool,  # Source pool (hub's pool when hub is sending)
                    "dataset": dataset,
                    "target_pool": target_pool,  # Target pool (receiving system's pool)
                    "target_dataset": dataset,
                    "starting_snapshot": incremental_base,
                    "ending_snapshot": snapshot_name,
                    "source_ssh_hostname": action.get("source_ssh_hostname"),
                    "target_ssh_hostname": action.get("target_ssh_hostname"),
                    "sync_group_id": action.get("sync_group_id"),
                }
            else:
                # Update ending snapshot if this snapshot is newer (lexical compare may suffice due to timestamp naming)
                if snapshot_name and snapshot_name > entry["ending_snapshot"]:
                    entry["ending_snapshot"] = snapshot_name
                # Prefer having a starting_snapshot if any incremental action exists
                if not entry["starting_snapshot"] and incremental_base:
                    entry["starting_snapshot"] = incremental_base
                # If target_pool becomes known later, set it
                if not entry["target_pool"] and target_pool:
                    entry["target_pool"] = target_pool

        # Validate and filter invalid instructions (same starting/ending snapshot, insufficient gap)
        valid_datasets = []
        for dataset, instruction in consolidated.items():
            starting = instruction.get("starting_snapshot")
            ending = instruction.get("ending_snapshot")

            # Skip if starting == ending (would fail zfs send -I)
            if starting and ending and starting == ending:
                logger.warning(
                    "Skipping invalid instruction: starting_snapshot == ending_snapshot (%s) "
                    "for dataset %s",
                    starting,
                    dataset,
                )
                self.diagnostics.append(
                    {
                        "level": "warning",
                        "message": f"Skipped instruction with same starting/ending snapshot: {starting}",
                        "dataset": dataset,
                    }
                )
                continue

            # Validate snapshot gap (72-hour minimum) for incremental syncs
            if starting and ending:
                # Build timestamp mapping from source snapshots
                source_timestamps: Dict[str, datetime] = {}
                for action in all_actions:
                    if action.get("dataset") == dataset:
                        source_id = UUID(action.get("source_system_id"))
                        snaps = self.snapshot_repo.get_by_dataset(
                            dataset=dataset, system_id=source_id
                        )
                        for s in snaps:
                            name = self.comparison_service.extract_snapshot_name(s.name)
                            source_timestamps[name] = s.timestamp
                        break

                if not validate_snapshot_gap(starting, ending, source_timestamps):
                    logger.debug(
                        "Skipping instruction for %s: insufficient time gap between "
                        "snapshots %s and %s",
                        dataset,
                        starting,
                        ending,
                    )
                    self.diagnostics.append(
                        {
                            "level": "info",
                            "message": (
                                f"Skipped instruction for {dataset}: insufficient time gap "
                                f"between {starting} and {ending}"
                            ),
                            "dataset": dataset,
                        }
                    )
                    continue

            valid_datasets.append(dataset)

        # Filter consolidated to only valid datasets
        consolidated = {k: v for k, v in consolidated.items() if k in valid_datasets}

        # Generate commands for each dataset instruction
        for instruction in consolidated.values():
            commands = []
            dataset = instruction["dataset"]
            starting_snapshot = instruction.get("starting_snapshot")
            ending_snapshot = instruction.get("ending_snapshot")
            source_ssh_hostname = instruction.get("source_ssh_hostname")
            target_ssh_hostname = instruction.get("target_ssh_hostname")

            if ending_snapshot and source_ssh_hostname and target_ssh_hostname:
                # Find source pool by looking up actions for this dataset
                source_pool = None
                for action in all_actions:
                    if action.get("dataset") == dataset:
                        source_pool = action.get("pool")  # This is the source pool from the action
                        break

                target_pool = instruction.get("target_pool")

                if source_pool and target_pool:
                    try:
                        if starting_snapshot:
                            # Incremental sync command
                            command = SSHCommandGenerator.generate_incremental_sync_command(
                                pool=source_pool,
                                dataset=dataset,
                                snapshot_name=ending_snapshot,
                                incremental_base=starting_snapshot,
                                target_ssh_hostname=target_ssh_hostname,
                                target_pool=target_pool,
                                target_dataset=dataset,
                            )
                            commands.append(command)
                        else:
                            # Full sync command
                            command = SSHCommandGenerator.generate_full_sync_command(
                                pool=source_pool,
                                dataset=dataset,
                                snapshot_name=ending_snapshot,
                                target_ssh_hostname=target_ssh_hostname,
                                target_pool=target_pool,
                                target_dataset=dataset,
                            )
                            commands.append(command)
                    except (ValueError, TypeError, AttributeError) as e:
                        logger.warning("Failed to generate sync command for %s: %s", dataset, e)

            instruction["commands"] = commands

        dataset_instructions = list(consolidated.values())
        logger.info(
            "Consolidated %d actions into %d dataset instructions for system %s",
            len(all_actions),
            len(dataset_instructions),
            system_id,
        )

        response: Dict[str, Any] = {
            "system_id": str(system_id),
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "datasets": dataset_instructions,
            "dataset_count": len(dataset_instructions),
        }

        if include_diagnostics:
            response["diagnostics"] = self.diagnostics

        return response

    def generate_dataset_sync_instructions(
        self,
        sync_group_id: UUID,
        system_id: Optional[UUID] = None,
        incremental_only: bool = False,
    ) -> List[Dict[str, Any]]:
        """Generate dataset-level sync instructions for a sync group.

        Args:
            sync_group_id: The sync group to process.
            system_id: If provided, limit instructions to actions targeting this system.
            incremental_only: If True, only include incremental actions (skip full sends).

        Returns:
            List of dataset instruction dicts matching `DatasetSyncInstruction` schema.
        """
        actions = self.determine_sync_actions(sync_group_id, system_id=system_id)
        # Consolidate per dataset
        consolidated: Dict[str, Dict[str, Any]] = {}
        for action in actions:
            if incremental_only and not action.get("is_incremental"):
                continue
            dataset = action.get("dataset")
            if not dataset:
                continue
            snapshot_name = action.get("snapshot_name")
            incremental_base = (
                action.get("incremental_base") if action.get("is_incremental") else None
            )
            target_pool = action.get("target_pool") or action.get("pool")
            entry = consolidated.get(dataset)
            if entry is None:
                consolidated[dataset] = {
                    "pool": target_pool,  # Use target_pool for the main instruction pool
                    "dataset": dataset,
                    "target_pool": target_pool,
                    "target_dataset": dataset,
                    "starting_snapshot": incremental_base,
                    "ending_snapshot": snapshot_name,
                    "source_ssh_hostname": action.get("source_ssh_hostname"),
                    "target_ssh_hostname": action.get("target_ssh_hostname"),
                    "sync_group_id": action.get("sync_group_id"),
                }
            else:
                if snapshot_name and snapshot_name > entry["ending_snapshot"]:
                    entry["ending_snapshot"] = snapshot_name
                if not entry["starting_snapshot"] and incremental_base:
                    entry["starting_snapshot"] = incremental_base
                if not entry["target_pool"] and target_pool:
                    entry["target_pool"] = target_pool
        return list(consolidated.values())

    def update_sync_state(
        self,
        sync_group_id: UUID,
        dataset: str,
        system_id: UUID,
        status: SyncStatus,
        error_message: Optional[str] = None,
    ) -> SyncStateModel:
        """
        Update or create a sync state record for a dataset.

        Returns the updated or created sync state.
        """
        # Check if sync state already exists
        existing = self.sync_state_repo.get_by_dataset(
            sync_group_id=sync_group_id, dataset=dataset, system_id=system_id
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
                dataset=dataset,
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

        status_counts: Dict[str, int] = {}
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
            "last_updated": max((s.last_check for s in sync_states if s.last_check), default=None),
        }

    def _get_datasets_for_systems(self, system_ids: List[UUID]) -> List[str]:
        """Get unique dataset names from snapshots for given systems."""
        datasets: Set[str] = set()
        for system_id in system_ids:
            snapshots = self.snapshot_repo.get_by_system(system_id)
            for snapshot in snapshots:
                datasets.add(snapshot.dataset)
        return list(datasets)

    def _find_snapshot_id_and_pool(
        self, dataset: str, snapshot_name: str, system_id: UUID
    ) -> Tuple[Optional[UUID], Optional[str]]:
        """
        Find snapshot_id and pool for a given snapshot name on a system.

        Returns the snapshot ID and pool if found, otherwise (None, None).
        """
        snapshots = self.snapshot_repo.get_by_dataset(dataset=dataset, system_id=system_id)
        for snapshot in snapshots:
            if self.comparison_service.extract_snapshot_name(snapshot.name) == snapshot_name:
                return snapshot.id, snapshot.pool
        logger.warning(
            "Could not find snapshot_id for %s on system %s for dataset %s",
            snapshot_name,
            system_id,
            dataset,
        )
        return None, None

    def _estimate_snapshot_size(
        self, dataset: str, snapshot_name: str, source_system_id: UUID
    ) -> Optional[int]:
        """Estimate the size of a snapshot for transfer planning."""
        snapshots = self.snapshot_repo.get_by_dataset(dataset=dataset, system_id=source_system_id)
        for snapshot in snapshots:
            if self.comparison_service.extract_snapshot_name(snapshot.name) == snapshot_name:
                return snapshot.size
        return None

    def _get_target_pool(self, dataset: str, target_system_id: UUID) -> Optional[str]:
        """Get the pool for a dataset on a target system."""
        target_snapshots = self.snapshot_repo.get_by_dataset(
            dataset=dataset, system_id=target_system_id
        )
        if target_snapshots:
            return target_snapshots[0].pool
        return None

    def _get_system_hostname(self, system_id: UUID) -> str:
        """
        Get hostname for a system, falling back to system ID if not found.

        Args:
            system_id: UUID of the system

        Returns:
            Hostname string, or system ID as string if system not found
        """
        system = self.system_repo.get(system_id)
        if system and system.hostname:
            return system.hostname
        return str(system_id)

    def _find_incremental_base(
        self,
        dataset: str,
        target_system_id: UUID,
        source_system_id: UUID,
    ) -> Optional[str]:
        """
        Find a common base snapshot for incremental send.

        Returns the snapshot name that exists on both systems and can serve as base,
        or None if no common base is found (full send required).
        """
        # Get all snapshots from both systems
        target_snapshots = self.snapshot_repo.get_by_dataset(
            dataset=dataset, system_id=target_system_id
        )
        source_snapshots = self.snapshot_repo.get_by_dataset(
            dataset=dataset, system_id=source_system_id
        )

        # Extract snapshot names (without pool/dataset prefix)
        target_names = {
            self.comparison_service.extract_snapshot_name(s.name): s.timestamp
            for s in target_snapshots
        }
        source_names = {
            self.comparison_service.extract_snapshot_name(s.name): s.timestamp
            for s in source_snapshots
        }

        # Find common snapshots, sorted by timestamp (most recent first)
        common_snapshots = [
            (name, timestamp) for name, timestamp in target_names.items() if name in source_names
        ]
        common_snapshots.sort(key=lambda x: x[1], reverse=True)

        # Return the most recent common snapshot if any exist
        if common_snapshots:
            return common_snapshots[0][0]

        return None

    def analyze_sync_group(self, sync_group_id: UUID) -> Dict[str, Any]:
        """
        Analyze a sync group to show all datasets, snapshot counts per system, and detected mismatches.

        Returns:
            Dictionary with:
            - sync_group_id: UUID of the sync group
            - systems: List of system info (id, hostname)
            - datasets: List of datasets with:
                - dataset_name: Name of the dataset
                - systems: List of system info with pool, snapshot_count, last_snapshot
                - sync_status: "in_sync" or "out_of_sync" based on snapshot comparison
                - mismatches: List of detected mismatches for this dataset
        """
        logger.info("Analyzing sync group %s", sync_group_id)

        sync_group = self.sync_group_repo.get(sync_group_id)
        if not sync_group:
            raise ValueError(f"Sync group '{sync_group_id}' not found")

        # Get all systems in the sync group
        system_ids = [assoc.system_id for assoc in sync_group.system_associations]
        systems_info = []
        for system_id in system_ids:
            system = self.system_repo.get(system_id)
            if system:
                systems_info.append({"system_id": str(system_id), "hostname": system.hostname})

        # Get all datasets for this sync group
        datasets = self._get_datasets_for_systems(system_ids)

        # Get detected mismatches
        mismatches = self.detect_sync_mismatches(sync_group_id=sync_group_id)

        # Group mismatches by dataset
        mismatches_by_dataset: Dict[str, List[Dict[str, Any]]] = {}
        for mismatch in mismatches:
            dataset_name = mismatch.get("dataset")
            if dataset_name:
                if dataset_name not in mismatches_by_dataset:
                    mismatches_by_dataset[dataset_name] = []
                mismatches_by_dataset[dataset_name].append(mismatch)

        # Build dataset analysis
        datasets_analysis = []

        for dataset_name in datasets:
            # Get snapshot counts per system
            dataset_systems = []
            system_snapshot_names: Dict[UUID, Set[str]] = {}
            for system_id in system_ids:
                snapshots = self.snapshot_repo.get_by_dataset(
                    dataset=dataset_name, system_id=system_id
                )
                last_snapshot = None
                pool = None
                if snapshots:
                    latest = max(snapshots, key=lambda s: s.timestamp)
                    last_snapshot = self.comparison_service.extract_snapshot_name(latest.name)
                    pool = latest.pool

                system = self.system_repo.get(system_id)
                dataset_systems.append(
                    {
                        "system_id": str(system_id),
                        "hostname": system.hostname if system else "unknown",
                        "pool": pool,
                        "snapshot_count": len(snapshots),
                        "last_snapshot": last_snapshot,
                    }
                )
                names = {self.comparison_service.extract_snapshot_name(s.name) for s in snapshots}
                system_snapshot_names[system_id] = names

            # Check if all systems have the same snapshots
            if system_snapshot_names:
                all_in_sync = all(
                    names == list(system_snapshot_names.values())[0]
                    for names in system_snapshot_names.values()
                )
                sync_status = "in_sync" if all_in_sync else "out_of_sync"
            else:
                sync_status = "no_snapshots"

            datasets_analysis.append(
                {
                    "dataset_name": dataset_name,
                    "systems": dataset_systems,
                    "sync_status": sync_status,
                    "mismatches": mismatches_by_dataset.get(dataset_name, []),
                }
            )

        return {
            "sync_group_id": str(sync_group_id),
            "sync_group_name": sync_group.name,
            "enabled": sync_group.enabled,
            "directional": sync_group.directional,
            "hub_system_id": str(sync_group.hub_system_id) if sync_group.hub_system_id else None,
            "systems": systems_info,
            "datasets": datasets_analysis,
            "total_datasets": len(datasets_analysis),
            "total_mismatches": len(mismatches),
        }
