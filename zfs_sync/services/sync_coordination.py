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
        self._orphan_datasets_logged: Set[Tuple[str, UUID]] = set()

    def detect_sync_mismatches(self, sync_group_id: UUID) -> List[Dict[str, Any]]:
        """
        Detect snapshot mismatches for a sync group.

        Returns a list of mismatches that need to be synchronized.
        Note: This detects missing snapshots, not conflicts. Use ConflictResolutionService
        to detect conflicts.
        """
        logger.info("Detecting sync mismatches for sync group %s", sync_group_id)

        sync_group = self.sync_group_repo.get(sync_group_id)
        if not sync_group:
            raise ValueError(
                f"Sync group '{sync_group_id}' not found. "
                f"Cannot detect sync mismatches for non-existent sync group."
            )

        if not sync_group.enabled:
            logger.info("Sync group %s is disabled", sync_group_id)
            return []

        # Get all systems in the sync group
        system_ids = [assoc.system_id for assoc in sync_group.system_associations]

        if len(system_ids) < 2:
            logger.warning("Sync group %s has less than 2 systems", sync_group_id)
            return []

        # Handle directional sync logic
        if sync_group.directional and sync_group.hub_system_id:
            hub_system_id = sync_group.hub_system_id
            if hub_system_id not in system_ids:
                logger.warning(
                    "Hub system %s not in sync group %s, falling back to bidirectional sync",
                    hub_system_id,
                    sync_group_id,
                )
                # Continue with bidirectional logic
            else:
                logger.info(
                    "Using directional sync for group %s with hub system %s",
                    sync_group_id,
                    hub_system_id,
                )

        # Get all systems for snapshot source checking (even in directional mode)
        all_system_ids = [assoc.system_id for assoc in sync_group.system_associations]

        # Handle directional sync logic
        if sync_group.directional and sync_group.hub_system_id:
            # For directional sync, check mismatches for both:
            # 1. Source systems missing snapshots from hub (hub -> sources)
            # 2. Hub system missing snapshots from sources (sources -> hub)
            hub_system_id = sync_group.hub_system_id
            source_system_ids = [
                sid for sid in all_system_ids if sid != hub_system_id
            ]  # Source systems for mismatch detection
            logger.debug(
                "Directional sync: hub_system_id=%s, source systems: %s",
                hub_system_id,
                [str(sid) for sid in source_system_ids],
            )
            # For dataset discovery, use all systems to find all datasets
            system_ids_for_datasets = all_system_ids
        else:
            source_system_ids = None
            hub_system_id = None
            system_ids_for_datasets = all_system_ids
            logger.debug(
                "Bidirectional sync: checking mismatches for all systems: %s",
                [str(sid) for sid in system_ids_for_datasets],
            )

        # Get all datasets that should be synced (from existing snapshots)
        # Use all systems to discover datasets, not just source systems
        datasets = self._get_datasets_for_systems(system_ids_for_datasets)
        logger.debug(
            "Found %d datasets for systems %s: %s",
            len(datasets),
            [str(sid) for sid in system_ids_for_datasets],
            datasets,
        )

        mismatches = []
        for dataset in datasets:
            if sync_group.directional and sync_group.hub_system_id and hub_system_id:
                # For directional sync, check mismatches in both directions:
                # 1. Source systems missing snapshots from hub (hub -> sources)
                # 2. Hub system missing snapshots from sources (sources -> hub)
                # hub_system_id and source_system_ids are already defined above
                logger.debug(
                    "Directional sync: checking dataset %s, hub=%s, sources=%s",
                    dataset,
                    hub_system_id,
                    [str(sid) for sid in source_system_ids],
                )

                # Get comparison for all systems to find what each system is missing
                comparison = self.comparison_service.compare_snapshots_by_dataset(
                    dataset=dataset, system_ids=all_system_ids
                )
                logger.debug(
                    "Comparison for dataset %s: missing_snapshots keys=%s",
                    dataset,
                    list(comparison.get("missing_snapshots", {}).keys()),
                )

                # 1. Create mismatches for source systems missing snapshots from hub
                for source_system_id in source_system_ids:
                    source_missing = comparison["missing_snapshots"].get(str(source_system_id), [])
                    logger.debug(
                        "Source system %s missing %d snapshots for dataset %s",
                        source_system_id,
                        len(source_missing),
                        dataset,
                    )

                    for missing_snapshot in source_missing:
                        # Check if hub or other sources have this snapshot
                        all_snapshots_except_source = set()
                        for sys_id in all_system_ids:
                            if sys_id != source_system_id:
                                sys_snapshots = self.snapshot_repo.get_by_dataset(
                                    dataset=dataset, system_id=sys_id
                                )
                                sys_snapshot_names = {
                                    self.comparison_service.extract_snapshot_name(s.name)
                                    for s in sys_snapshots
                                }
                                all_snapshots_except_source.update(sys_snapshot_names)

                        # Prefer hub as source, but allow other sources if hub doesn't have it
                        if missing_snapshot in all_snapshots_except_source:
                            # Check if hub has this snapshot
                            hub_snapshots = self.snapshot_repo.get_by_dataset(
                                dataset=dataset, system_id=hub_system_id
                            )
                            hub_snapshot_names = {
                                self.comparison_service.extract_snapshot_name(s.name)
                                for s in hub_snapshots
                            }
                            if missing_snapshot in hub_snapshot_names:
                                # Hub has it, create mismatch with hub as source
                                mismatch = {
                                    "sync_group_id": str(sync_group_id),
                                    "dataset": dataset,
                                    "target_system_id": str(source_system_id),
                                    "missing_snapshot": missing_snapshot,
                                    "source_system_ids": [str(hub_system_id)],
                                    "priority": self._calculate_priority(
                                        missing_snapshot, comparison
                                    ),
                                    "directional": True,
                                    "reason": "source_missing_from_hub",
                                }
                                mismatches.append(mismatch)
                                logger.debug(
                                    "Created mismatch: target=%s (source), snapshot=%s, source=%s (hub)",
                                    source_system_id,
                                    missing_snapshot,
                                    hub_system_id,
                                )
                            else:
                                # Hub doesn't have it, but another source does - create mismatch with that source
                                source_systems_with_snapshot = self._find_systems_with_snapshot(
                                    dataset, missing_snapshot, source_system_ids
                                )
                                if source_systems_with_snapshot:
                                    mismatch = {
                                        "sync_group_id": str(sync_group_id),
                                        "dataset": dataset,
                                        "target_system_id": str(source_system_id),
                                        "missing_snapshot": missing_snapshot,
                                        "source_system_ids": [str(sid) for sid in source_systems_with_snapshot],
                                        "priority": self._calculate_priority(
                                            missing_snapshot, comparison
                                        ),
                                        "directional": True,
                                        "reason": "source_missing_from_other_source",
                                    }
                                    mismatches.append(mismatch)
                                    logger.debug(
                                        "Created mismatch: target=%s (source), snapshot=%s, source=%s (other source)",
                                        source_system_id,
                                        missing_snapshot,
                                        source_systems_with_snapshot[0],
                                    )

                # 2. Create mismatches for hub system missing snapshots from sources
                hub_missing = comparison["missing_snapshots"].get(str(hub_system_id), [])
                logger.debug(
                    "Hub system %s missing %d snapshots for dataset %s",
                    hub_system_id,
                    len(hub_missing),
                    dataset,
                )

                for missing_snapshot in hub_missing:
                    # Find which source systems have this snapshot
                    source_systems_with_snapshot = self._find_systems_with_snapshot(
                        dataset, missing_snapshot, source_system_ids
                    )
                    if source_systems_with_snapshot:
                        mismatch = {
                            "sync_group_id": str(sync_group_id),
                            "dataset": dataset,
                            "target_system_id": str(hub_system_id),
                            "missing_snapshot": missing_snapshot,
                            "source_system_ids": [str(sid) for sid in source_systems_with_snapshot],
                            "priority": self._calculate_priority(missing_snapshot, comparison),
                            "directional": True,
                            "reason": "hub_missing_from_source",
                        }
                        mismatches.append(mismatch)
                        logger.debug(
                            "Created mismatch: target=%s (hub), snapshot=%s, source=%s",
                            hub_system_id,
                            missing_snapshot,
                            source_systems_with_snapshot[0],
                        )
            else:
                # Bidirectional sync: existing logic
                comparison = self.comparison_service.compare_snapshots_by_dataset(
                    dataset=dataset, system_ids=system_ids
                )

                # Find systems with missing snapshots
                for system_id_str, missing_snapshots in comparison["missing_snapshots"].items():
                    if missing_snapshots:
                        system_id = UUID(system_id_str)
                        logger.debug(
                            "System %s missing %d snapshots for dataset %s",
                            system_id,
                            len(missing_snapshots),
                            dataset,
                        )
                        for missing_snapshot in missing_snapshots:
                            # Find which systems have this snapshot
                            source_systems = self._find_systems_with_snapshot(
                                dataset, missing_snapshot, system_ids
                            )

                            if source_systems:
                                mismatch = {
                                    "sync_group_id": str(sync_group_id),
                                    "dataset": dataset,
                                    "target_system_id": str(system_id),
                                    "missing_snapshot": missing_snapshot,
                                    "source_system_ids": [str(sid) for sid in source_systems],
                                    "priority": self._calculate_priority(
                                        missing_snapshot, comparison
                                    ),
                                    "directional": False,
                                    "reason": "bidirectional_mismatch",
                                }
                                mismatches.append(mismatch)
                                logger.debug(
                                    "Created mismatch: target=%s, snapshot=%s, sources=%s",
                                    system_id,
                                    missing_snapshot,
                                    source_systems,
                                )

        logger.info(
            "Detected %d mismatches for sync group %s (directional=%s)",
            len(mismatches),
            sync_group_id,
            sync_group.directional if sync_group else False,
        )
        if mismatches:
            target_systems = {m["target_system_id"] for m in mismatches}
            logger.debug("Mismatches target systems: %s", target_systems)

        return mismatches

    def determine_sync_actions(
        self, sync_group_id: UUID, system_id: Optional[UUID] = None
    ) -> List[Dict[str, Any]]:
        """
        Determine sync actions needed for a sync group or specific system.

        Returns a list of actions that should be performed.
        """
        logger.info("Determining sync actions for sync group %s", sync_group_id)

        mismatches = self.detect_sync_mismatches(sync_group_id)
        logger.debug("Found %d total mismatches", len(mismatches))

        if system_id:
            # Filter to actions for specific system
            mismatches_before_filter = len(mismatches)
            mismatches = [m for m in mismatches if UUID(m["target_system_id"]) == system_id]
            logger.debug(
                "Filtered mismatches for system %s: %d -> %d",
                system_id,
                mismatches_before_filter,
                len(mismatches),
            )
            if mismatches_before_filter > 0 and len(mismatches) == 0:
                logger.warning(
                    "No mismatches target system %s. Mismatches target: %s",
                    system_id,
                    {m["target_system_id"] for m in self.detect_sync_mismatches(sync_group_id)},
                )

        actions = []
        for mismatch in mismatches:
            source_system_id = UUID(mismatch["source_system_ids"][0])  # Use first available
            target_system_id = UUID(mismatch["target_system_id"])
            dataset = mismatch["dataset"]

            # Get source system for SSH details
            source_system = self.system_repo.get(source_system_id)
            if not source_system:
                logger.warning("Source system %s not found, skipping action", source_system_id)
                continue

            # Find snapshot_id and pool from source system
            snapshot_id, pool = self._find_snapshot_id_and_pool(
                dataset=dataset,
                snapshot_name=mismatch["missing_snapshot"],
                system_id=source_system_id,
            )

            if not pool:
                self.diagnostics.append(
                    {
                        "dataset": dataset,
                        "reason": f"Could not determine pool for snapshot {mismatch['missing_snapshot']} on source system {source_system_id}.",
                        "skipped_action": "generate_sync_command",
                    }
                )
                logger.warning(
                    "Could not determine pool for snapshot %s on system %s, skipping action",
                    mismatch["missing_snapshot"],
                    source_system_id,
                )
                continue

            # Check if incremental send is possible
            incremental_base = self._find_incremental_base(
                dataset=dataset,
                target_system_id=target_system_id,
                source_system_id=source_system_id,
            )
            is_incremental = incremental_base is not None

            # Determine target system and pool
            sync_command = None
            target_system = self.system_repo.get(target_system_id)
            target_pool = (
                self._get_target_pool(dataset, target_system_id) if target_system else None
            )

            # Generate sync command if target SSH details and pool are available
            if target_system and target_system.ssh_hostname and target_pool:
                try:
                    if is_incremental and incremental_base:
                        sync_command = SSHCommandGenerator.generate_incremental_sync_command(
                            pool=pool,
                            dataset=dataset,
                            snapshot_name=mismatch["missing_snapshot"],
                            incremental_base=incremental_base,
                            target_ssh_hostname=target_system.ssh_hostname,
                            target_pool=target_pool,
                            target_dataset=dataset,
                        )
                    else:
                        sync_command = SSHCommandGenerator.generate_full_sync_command(
                            pool=pool,
                            dataset=dataset,
                            snapshot_name=mismatch["missing_snapshot"],
                            target_ssh_hostname=target_system.ssh_hostname,
                            target_pool=target_pool,
                            target_dataset=dataset,
                        )
                except (ValueError, TypeError, AttributeError) as e:
                    logger.warning("Failed to generate sync command: %s", e)
                    self.diagnostics.append(
                        {
                            "dataset": dataset,
                            "reason": f"Failed to generate sync command: {e}",
                            "skipped_action": "generate_sync_command",
                        }
                    )
            elif target_system and not target_pool:
                # Orphan dataset scenario: target has no snapshots yet
                orphan_key = (dataset, target_system_id)
                if (
                    self.settings.suppress_orphan_dataset_logs
                    and orphan_key in self._orphan_datasets_logged
                ):
                    # Skip repeated logging/diagnostics
                    pass
                else:
                    self.diagnostics.append(
                        {
                            "dataset": dataset,
                            "reason": f"Target system {target_system_id} has no snapshots for dataset {dataset} yet (orphan).",
                            "skipped_action": "generate_sync_command",
                        }
                    )
                    logger.warning(
                        "Orphan dataset: no target pool for %s on system %s (suppressed=%s)",
                        dataset,
                        target_system_id,
                        self.settings.suppress_orphan_dataset_logs,
                    )
                    self._orphan_datasets_logged.add(orphan_key)

            action = {
                "action_type": "sync_snapshot",
                "sync_group_id": mismatch["sync_group_id"],
                "pool": pool,
                "target_pool": target_pool,
                "dataset": dataset,
                "target_system_id": mismatch["target_system_id"],
                "source_system_id": mismatch["source_system_ids"][0],  # Use first available
                "snapshot_name": mismatch["missing_snapshot"],
                "snapshot_id": str(snapshot_id) if snapshot_id else None,
                "priority": mismatch["priority"],
                "estimated_size": self._estimate_snapshot_size(
                    dataset=dataset,
                    snapshot_name=mismatch["missing_snapshot"],
                    source_system_id=source_system_id,
                ),
                "source_ssh_hostname": source_system.ssh_hostname,
                "source_ssh_user": source_system.ssh_user,
                "source_ssh_port": source_system.ssh_port,
                "target_ssh_hostname": target_system.ssh_hostname if target_system else None,
                "sync_command": sync_command,
                "incremental_base": incremental_base,
                "is_incremental": is_incremental,
            }
            actions.append(action)

        # Sort by priority (higher priority first)
        actions.sort(key=lambda x: x["priority"], reverse=True)

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
            self.diagnostics.append(
                {
                    "level": "warning",
                    "message": f"No sync actions found for system {system_id}",
                    "sync_groups_checked": len(sync_groups),
                    "suggestion": "Check if system is hub in directional sync (hub systems may not receive instructions)",
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
            target_pool = action.get("target_pool") or action.get("pool")

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
                # Update ending snapshot if this snapshot is newer (lexical compare may suffice due to timestamp naming)
                if snapshot_name and snapshot_name > entry["ending_snapshot"]:
                    entry["ending_snapshot"] = snapshot_name
                # Prefer having a starting_snapshot if any incremental action exists
                if not entry["starting_snapshot"] and incremental_base:
                    entry["starting_snapshot"] = incremental_base
                # If target_pool becomes known later, set it
                if not entry["target_pool"] and target_pool:
                    entry["target_pool"] = target_pool

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

    def _find_systems_with_snapshot(
        self, dataset: str, snapshot_name: str, system_ids: List[UUID]
    ) -> List[UUID]:
        """Find which systems have a specific snapshot."""
        systems_with_snapshot = []
        for system_id in system_ids:
            snapshots = self.snapshot_repo.get_by_dataset(dataset=dataset, system_id=system_id)
            for snapshot in snapshots:
                if self.comparison_service.extract_snapshot_name(snapshot.name) == snapshot_name:
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
        for latest_info in latest_snapshots.values():
            latest_snapshot_name = self.comparison_service.extract_snapshot_name(
                latest_info.get("name", "")
            )
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
