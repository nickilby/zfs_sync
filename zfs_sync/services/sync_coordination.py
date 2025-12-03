"""Service for coordinating snapshot synchronization across systems."""

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set
from uuid import UUID

from sqlalchemy.orm import Session

from zfs_sync.database.models import SnapshotModel, SyncStateModel
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
from zfs_sync.services.sync_queries import (
    calculate_priority,
    estimate_snapshot_size,
    find_incremental_base_by_dataset_name,
    find_snapshot_id,
    get_datasets_for_systems,
)
from zfs_sync.services.sync_validators import (
    MIN_SNAPSHOT_GAP_HOURS,
    is_midnight_snapshot,
    is_snapshot_out_of_sync_by_72h,
    validate_snapshot_exists,
    validate_snapshot_gap,
)

logger = get_logger(__name__)


class SyncCoordinationService:
    """Service for coordinating snapshot synchronization."""

    # Minimum time gap between starting and ending snapshots (24 hours)
    MIN_SNAPSHOT_GAP_HOURS = MIN_SNAPSHOT_GAP_HOURS

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

        # Get all datasets that should be synced (grouped by dataset name, ignoring pool)
        dataset_mappings = get_datasets_for_systems(system_ids, self.snapshot_repo)

        mismatches = []
        for dataset_name, pool_systems in dataset_mappings.items():
            # Get all snapshots for this dataset name across all systems (regardless of pool)
            all_snapshots_by_system: Dict[UUID, List[SnapshotModel]] = {}
            pool_by_system: Dict[UUID, str] = {}

            for pool, system_id in pool_systems:
                pool_by_system[system_id] = pool
                snapshots = self.snapshot_repo.get_by_pool_dataset(
                    pool=pool, dataset=dataset_name, system_id=system_id
                )
                all_snapshots_by_system[system_id] = snapshots

            # Extract snapshot names (normalized) for comparison
            system_snapshot_names: Dict[UUID, Set[str]] = {}
            for system_id, snapshots in all_snapshots_by_system.items():
                names = {self.comparison_service._extract_snapshot_name(s.name) for s in snapshots}
                system_snapshot_names[system_id] = names

            if not system_snapshot_names:
                continue

            # Find all unique snapshot names across all systems
            all_snapshot_names = (
                set.union(*system_snapshot_names.values()) if system_snapshot_names else set()
            )

            # Find missing snapshots per system
            for target_system_id, target_names in system_snapshot_names.items():
                missing_snapshots = sorted(list(all_snapshot_names - target_names))

                if not missing_snapshots:
                    continue

                # Find which systems have the missing snapshots
                source_systems = []
                for source_system_id, source_names in system_snapshot_names.items():
                    if source_system_id == target_system_id:
                        continue
                    # Check if source has any of the missing snapshots
                    if any(name in source_names for name in missing_snapshots):
                        source_systems.append(source_system_id)

                if source_systems:
                    # Use first source system for pool information
                    source_system_id = source_systems[0]
                    source_pool = pool_by_system[source_system_id]
                    target_pool = pool_by_system[target_system_id]

                    # Create a comparison-like dict for priority calculation
                    comparison_dict = {
                        "missing_snapshots": {
                            str(sid): sorted(list(all_snapshot_names - names))
                            for sid, names in system_snapshot_names.items()
                        },
                        "latest_snapshots": {
                            str(sid): {
                                "name": max(
                                    all_snapshots_by_system[sid],
                                    key=lambda s: s.timestamp,  # type: ignore[arg-type,return-value]
                                ).name,
                                "timestamp": max(
                                    all_snapshots_by_system[sid],
                                    key=lambda s: s.timestamp,  # type: ignore[arg-type,return-value]
                                ).timestamp.isoformat(),
                            }
                            for sid in system_snapshot_names.keys()
                            if all_snapshots_by_system[sid]
                        },
                    }

                    for missing_snapshot in missing_snapshots:
                        mismatches.append(
                            {
                                "sync_group_id": str(sync_group_id),
                                "pool": source_pool,  # Source pool
                                "dataset": dataset_name,
                                "target_pool": target_pool,  # Target pool
                                "target_system_id": str(target_system_id),
                                "missing_snapshot": missing_snapshot,
                                "source_system_ids": [str(sid) for sid in source_systems],
                                "priority": calculate_priority(
                                    missing_snapshot, comparison_dict, self.comparison_service
                                ),
                            }
                        )

        return mismatches

    def determine_sync_actions(
        self,
        sync_group_id: UUID,
        system_id: Optional[UUID] = None,
        incremental_only: bool = False,
    ) -> List[Dict[str, Any]]:
        """
        Determine sync actions needed for a sync group or specific system.

        Returns a list of actions that should be performed.
        """
        logger.info("Determining sync actions for sync group %s", sync_group_id)

        mismatches = self.detect_sync_mismatches(sync_group_id)

        if system_id:
            # Filter to actions for specific system
            mismatches = [m for m in mismatches if UUID(m["target_system_id"]) == system_id]

        actions = []
        for mismatch in mismatches:
            source_system_id = UUID(mismatch["source_system_ids"][0])  # Use first available
            target_system_id = UUID(mismatch["target_system_id"])

            # Get source system for SSH details
            source_system = self.system_repo.get(source_system_id)
            if not source_system:
                logger.warning("Source system %s not found, skipping action", source_system_id)
                continue

            # Find snapshot_id from source system
            snapshot_id = find_snapshot_id(
                pool=mismatch["pool"],
                dataset=mismatch["dataset"],
                snapshot_name=mismatch["missing_snapshot"],
                system_id=source_system_id,
                snapshot_repo=self.snapshot_repo,
                comparison_service=self.comparison_service,
            )

            # Check if incremental send is possible
            # Use target_pool if available (from pool-agnostic mismatch detection)
            target_pool = mismatch.get("target_pool", mismatch["pool"])
            incremental_base = find_incremental_base_by_dataset_name(
                dataset_name=mismatch["dataset"],
                target_system_id=target_system_id,
                target_pool=target_pool,
                source_system_id=source_system_id,
                source_pool=mismatch["pool"],
                snapshot_repo=self.snapshot_repo,
                comparison_service=self.comparison_service,
            )
            is_incremental = incremental_base is not None

            # Filter out full syncs if incremental_only is True
            if incremental_only and not is_incremental:
                logger.debug(
                    "Skipping full sync for %s/%s@%s (incremental_only=True)",
                    mismatch["pool"],
                    mismatch["dataset"],
                    mismatch["missing_snapshot"],
                )
                continue

            # Generate sync command if target SSH details are available
            # Command runs on source system, pipes to target via SSH
            sync_command = None
            target_system = self.system_repo.get(target_system_id)
            if target_system and target_system.ssh_hostname:
                try:
                    # Get target pool from mismatch (may be different from source pool)
                    target_pool = mismatch.get("target_pool", mismatch["pool"])
                    if is_incremental and incremental_base:
                        sync_command = SSHCommandGenerator.generate_incremental_sync_command(
                            pool=mismatch["pool"],
                            dataset=mismatch["dataset"],
                            snapshot_name=mismatch["missing_snapshot"],
                            incremental_base=incremental_base,
                            target_ssh_hostname=target_system.ssh_hostname,
                            target_pool=target_pool,
                            target_dataset=mismatch["dataset"],
                        )
                    else:
                        sync_command = SSHCommandGenerator.generate_full_sync_command(
                            pool=mismatch["pool"],
                            dataset=mismatch["dataset"],
                            snapshot_name=mismatch["missing_snapshot"],
                            target_ssh_hostname=target_system.ssh_hostname,
                            target_pool=target_pool,
                            target_dataset=mismatch["dataset"],
                        )
                except (ValueError, TypeError, AttributeError) as e:
                    logger.warning("Failed to generate sync command: %s", e)

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
                "estimated_size": estimate_snapshot_size(
                    mismatch["pool"],
                    mismatch["dataset"],
                    mismatch["missing_snapshot"],
                    source_system_id,
                    self.snapshot_repo,
                    self.comparison_service,
                ),
                "source_ssh_hostname": source_system.ssh_hostname,
                "source_ssh_user": source_system.ssh_user,
                "source_ssh_port": source_system.ssh_port,
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
        Get sync instructions for a system.

        Returns dataset-grouped instructions for what snapshots need to be synced.
        """
        logger.info("Getting sync instructions for system %s", system_id)

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

        all_datasets = []
        all_diagnostics = []
        for group in sync_groups:
            if group:
                dataset_result = self.generate_dataset_sync_instructions(
                    sync_group_id=group.id,
                    system_id=system_id,
                    incremental_only=True,
                    include_diagnostics=include_diagnostics,
                )
                all_datasets.extend(dataset_result.get("datasets", []))
                if include_diagnostics and "diagnostics" in dataset_result:
                    all_diagnostics.extend(dataset_result["diagnostics"])

        result = {
            "system_id": str(system_id),
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "datasets": all_datasets,
            "dataset_count": len(all_datasets),
        }

        if include_diagnostics:
            result["diagnostics"] = all_diagnostics

        return result

    def initialize_sync_states_for_group(self, sync_group_id: UUID) -> Dict[str, Any]:
        """
        Initialize sync states for all datasets in a sync group.

        Creates sync states for ALL datasets in the sync group, marking them as
        IN_SYNC if all systems have the same snapshots, OUT_OF_SYNC otherwise.

        Returns:
            Dictionary with summary of initialized states
        """
        logger.info("Initializing sync states for sync group %s", sync_group_id)

        sync_group = self.sync_group_repo.get(sync_group_id)
        if not sync_group:
            raise ValueError(f"Sync group '{sync_group_id}' not found")

        # Get all systems in the sync group
        system_ids = [assoc.system_id for assoc in sync_group.system_associations]

        if len(system_ids) < 2:
            logger.warning(
                "Sync group %s has less than 2 systems, skipping initialization", sync_group_id
            )
            return {"initialized": 0, "datasets": []}

        # Get all datasets for this sync group
        dataset_mappings = get_datasets_for_systems(system_ids, self.snapshot_repo)

        initialized_count = 0
        datasets_processed = []

        for dataset_name, pool_systems in dataset_mappings.items():
            # Get all snapshots for this dataset across all systems (pool-agnostic)
            all_snapshots_by_system: Dict[UUID, List[SnapshotModel]] = {}
            for pool, system_id in pool_systems:
                snapshots = self.snapshot_repo.get_by_pool_dataset(
                    pool=pool, dataset=dataset_name, system_id=system_id
                )
                if system_id not in all_snapshots_by_system:
                    all_snapshots_by_system[system_id] = []
                all_snapshots_by_system[system_id].extend(snapshots)

            # Extract snapshot names (normalized) for comparison
            system_snapshot_names: Dict[UUID, Set[str]] = {}
            for system_id, snapshots in all_snapshots_by_system.items():
                names = {self.comparison_service._extract_snapshot_name(s.name) for s in snapshots}
                system_snapshot_names[system_id] = names

            if not system_snapshot_names:
                # No snapshots found, mark all systems as OUT_OF_SYNC
                for system_id in system_ids:
                    self.update_sync_state(
                        sync_group_id=sync_group_id,
                        dataset=dataset_name,
                        system_id=system_id,
                        status=SyncStatus.OUT_OF_SYNC,
                    )
                    initialized_count += 1
                datasets_processed.append({"dataset": dataset_name, "status": "no_snapshots"})
                continue

            # Check if all systems have the same snapshots
            all_in_sync = all(
                names == system_snapshot_names[list(system_snapshot_names.keys())[0]]
                for names in system_snapshot_names.values()
            )

            # Create/update sync states for all systems
            for system_id in system_ids:
                if system_id in system_snapshot_names:
                    # System has snapshots for this dataset
                    status = SyncStatus.IN_SYNC if all_in_sync else SyncStatus.OUT_OF_SYNC
                else:
                    # System has no snapshots for this dataset
                    status = SyncStatus.OUT_OF_SYNC

                self.update_sync_state(
                    sync_group_id=sync_group_id,
                    dataset=dataset_name,
                    system_id=system_id,
                    status=status,
                )
                initialized_count += 1

            dataset_info: Dict[str, Any] = {
                "dataset": dataset_name,
                "status": "in_sync" if all_in_sync else "out_of_sync",
                "systems": len(system_snapshot_names),
            }
            datasets_processed.append(dataset_info)

        logger.info(
            "Initialized %d sync states for %d datasets in sync group %s",
            initialized_count,
            len(datasets_processed),
            sync_group_id,
        )

        return {
            "sync_group_id": str(sync_group_id),
            "initialized": initialized_count,
            "datasets": datasets_processed,
        }

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
            # SQLAlchemy model attributes accept actual values at runtime, not Column types
            existing.status = status.value  # type: ignore
            existing.last_check = datetime.now(timezone.utc)  # type: ignore
            if status == SyncStatus.IN_SYNC:
                existing.last_sync = datetime.now(timezone.utc)  # type: ignore
            if error_message:
                existing.error_message = error_message  # type: ignore
            else:
                existing.error_message = None  # type: ignore
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
        system_repo = SystemRepository(self.db)
        systems_info = []
        for system_id in system_ids:
            system = system_repo.get(system_id)
            if system:
                systems_info.append({"system_id": str(system_id), "hostname": system.hostname})

        # Get all datasets for this sync group
        dataset_mappings = get_datasets_for_systems(system_ids, self.snapshot_repo)

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
        comparison_service = SnapshotComparisonService(self.db)

        for dataset_name, pool_systems in dataset_mappings.items():
            # Get snapshot counts per system
            dataset_systems = []
            for pool, system_id in pool_systems:
                snapshots = self.snapshot_repo.get_by_pool_dataset(
                    pool=pool, dataset=dataset_name, system_id=system_id
                )
                last_snapshot = None
                if snapshots:
                    latest = max(snapshots, key=lambda s: s.timestamp)
                    last_snapshot = comparison_service._extract_snapshot_name(latest.name)

                system = system_repo.get(system_id)
                dataset_systems.append(
                    {
                        "system_id": str(system_id),
                        "hostname": system.hostname if system else "unknown",
                        "pool": pool,
                        "snapshot_count": len(snapshots),
                        "last_snapshot": last_snapshot,
                    }
                )

            # Determine sync status by comparing snapshot names
            system_snapshot_names: Dict[UUID, Set[str]] = {}
            for pool, system_id in pool_systems:
                snapshots = self.snapshot_repo.get_by_pool_dataset(
                    pool=pool, dataset=dataset_name, system_id=system_id
                )
                names = {comparison_service._extract_snapshot_name(s.name) for s in snapshots}
                system_snapshot_names[system_id] = names

            # Check if all systems have the same snapshots
            if system_snapshot_names:
                all_in_sync = all(
                    names == system_snapshot_names[list(system_snapshot_names.keys())[0]]
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
            "systems": systems_info,
            "datasets": datasets_analysis,
            "total_datasets": len(datasets_analysis),
            "total_mismatches": len(mismatches),
        }

    def generate_dataset_sync_instructions(
        self,
        sync_group_id: UUID,
        system_id: Optional[UUID] = None,
        incremental_only: bool = True,
        include_diagnostics: bool = False,
    ) -> Dict[str, Any]:
        """
        Generate dataset-grouped sync instructions for a sync group or specific system.

        Groups missing snapshots by dataset and returns simplified format with
        starting and ending snapshots for incremental range sends.

        Guardrails:
        - Only syncs datasets that are more than 24 hours out of sync
        - Only uses midnight snapshots (ending in -000000)
        - Validates that snapshots exist in the database before using them
        - Ensures starting snapshot is older than ending snapshot
        - Requires minimum 24-hour gap between starting and ending snapshots

        Returns a dictionary with dataset-grouped instructions.
        """
        logger.info(
            "Generating dataset sync instructions for sync group %s, system_id=%s, incremental_only=%s",
            sync_group_id,
            system_id,
            incremental_only,
        )

        sync_group = self.sync_group_repo.get(sync_group_id)
        if not sync_group:
            raise ValueError(f"Sync group '{sync_group_id}' not found")

        if not sync_group.enabled:
            logger.info("Sync group %s is disabled", sync_group_id)
            return {"datasets": [], "dataset_count": 0}

        # Get all systems in the sync group
        system_ids = [assoc.system_id for assoc in sync_group.system_associations]

        if len(system_ids) < 2:
            logger.warning("Sync group %s has less than 2 systems", sync_group_id)
            return {"datasets": [], "dataset_count": 0}

        # Filter to source system if specified (system_id is the SOURCE who will send)
        # Instructions go to the SOURCE system, not the target
        if system_id:
            if system_id not in system_ids:
                logger.warning("System %s is not in sync group %s", system_id, sync_group_id)
                return {"datasets": [], "dataset_count": 0}
            source_system_ids = [system_id]
        else:
            source_system_ids = system_ids

        # Initialize sync states for all datasets in the sync group
        # This ensures sync states exist for all datasets, not just those with mismatches
        self.initialize_sync_states_for_group(sync_group_id)

        # Get all datasets that should be synced (grouped by dataset name, ignoring pool)
        dataset_mappings = get_datasets_for_systems(system_ids, self.snapshot_repo)

        dataset_instructions = []
        diagnostics: List[Dict[str, Any]] = [] if include_diagnostics else []

        for dataset_name, pool_systems in dataset_mappings.items():
            try:
                # Get all snapshots for this dataset name across all systems (regardless of pool)
                all_snapshots_by_system: Dict[UUID, List[SnapshotModel]] = {}
                pool_by_system: Dict[UUID, str] = {}

                for pool, system_id in pool_systems:
                    pool_by_system[system_id] = pool
                    snapshots = self.snapshot_repo.get_by_pool_dataset(
                        pool=pool, dataset=dataset_name, system_id=system_id
                    )
                    all_snapshots_by_system[system_id] = snapshots

                # Extract snapshot names (normalized) for comparison - only midnight snapshots
                system_snapshot_names: Dict[UUID, Set[str]] = {}
                for system_id, snapshots in all_snapshots_by_system.items():
                    names = {
                        self.comparison_service._extract_snapshot_name(s.name)
                        for s in snapshots
                        if is_midnight_snapshot(
                            self.comparison_service._extract_snapshot_name(s.name)
                        )
                    }
                    system_snapshot_names[system_id] = names

                if not system_snapshot_names:
                    reason = "no midnight snapshots found on any system"
                    logger.info(
                        "Skipping dataset %s: %s in sync group %s",
                        dataset_name,
                        reason,
                        sync_group_id,
                    )
                    if include_diagnostics:
                        diagnostics.append(
                            {
                                "dataset": dataset_name,
                                "reason": reason,
                                "guardrail": "midnight_snapshot_filter",
                            }
                        )
                    continue

                # Process each SOURCE system (who will send snapshots)
                for source_system_id in source_system_ids:
                    if source_system_id not in system_snapshot_names:
                        logger.info(
                            "Skipping source system %s for dataset %s: no midnight snapshots found",
                            source_system_id,
                            dataset_name,
                        )
                        continue

                    source_names = system_snapshot_names[source_system_id]
                    source_pool = pool_by_system[source_system_id]

                    # Find target systems that are missing snapshots from this source
                    for target_system_id in system_ids:
                        if target_system_id == source_system_id:
                            continue
                        if target_system_id not in system_snapshot_names:
                            logger.info(
                                "Skipping target system %s for dataset %s: no midnight snapshots found",
                                target_system_id,
                                dataset_name,
                            )
                            continue

                        target_names = system_snapshot_names[target_system_id]
                        missing_snapshots = sorted(list(source_names - target_names))

                        if not missing_snapshots:
                            # Target has all snapshots from source - in sync
                            self.update_sync_state(
                                sync_group_id=sync_group_id,
                                dataset=dataset_name,
                                system_id=target_system_id,
                                status=SyncStatus.IN_SYNC,
                            )
                            continue

                        target_pool = pool_by_system[target_system_id]

                        # GUARDRAIL 1: Check if datasets are more than 72 hours out of sync
                        source_snapshots = all_snapshots_by_system[source_system_id]
                        target_snapshots = all_snapshots_by_system[target_system_id]

                        if not is_snapshot_out_of_sync_by_72h(
                            source_snapshots=source_snapshots,
                            target_snapshots=target_snapshots,
                            source_snapshot_names=source_names,
                            target_snapshot_names=target_names,
                            comparison_service=self.comparison_service,
                        ):
                            reason = "not more than 72 hours out of sync"
                            logger.info(
                                "GUARDRAIL 1: Skipping %s from source %s to target %s (%s)",
                                dataset_name,
                                source_system_id,
                                target_system_id,
                                reason,
                            )
                            if include_diagnostics:
                                diagnostics.append(
                                    {
                                        "dataset": dataset_name,
                                        "source_system_id": str(source_system_id),
                                        "target_system_id": str(target_system_id),
                                        "reason": reason,
                                        "guardrail": "24_hour_out_of_sync_check",
                                    }
                                )
                            continue

                        # Find starting snapshot (most recent common midnight snapshot)
                        starting_snapshot = find_incremental_base_by_dataset_name(
                            dataset_name=dataset_name,
                            target_system_id=target_system_id,
                            target_pool=target_pool,
                            source_system_id=source_system_id,
                            source_pool=source_pool,
                            snapshot_repo=self.snapshot_repo,
                            comparison_service=self.comparison_service,
                        )

                        # FIX: If no common base but incremental_only, try to find oldest target snapshot that exists on source
                        if incremental_only and not starting_snapshot:
                            # Try to find oldest target midnight snapshot that also exists on source
                            target_snapshots = all_snapshots_by_system[target_system_id]
                            target_midnight_snapshots = [
                                s
                                for s in target_snapshots
                                if is_midnight_snapshot(
                                    self.comparison_service._extract_snapshot_name(s.name)
                                )
                            ]

                            if target_midnight_snapshots:
                                # Sort by timestamp (oldest first)
                                target_midnight_snapshots.sort(key=lambda s: s.timestamp)

                                # Check each target snapshot to see if it exists on source
                                for target_snap in target_midnight_snapshots:
                                    target_snap_name = (
                                        self.comparison_service._extract_snapshot_name(
                                            target_snap.name
                                        )
                                    )
                                    if target_snap_name in source_names:
                                        starting_snapshot = target_snap_name
                                        logger.info(
                                            "Using oldest common midnight snapshot %s as base for %s from source %s to target %s "
                                            "(no more recent common base found)",
                                            starting_snapshot,
                                            dataset_name,
                                            source_system_id,
                                            target_system_id,
                                        )
                                        break

                            if not starting_snapshot:
                                reason = (
                                    f"no common base midnight snapshot (incremental_only=True). "
                                    f"Source has {len(source_names)} midnight snapshots, target has {len(target_names)} midnight snapshots"
                                )
                                logger.info(
                                    "GUARDRAIL 2: Skipping %s from source %s to target %s (%s)",
                                    dataset_name,
                                    source_system_id,
                                    target_system_id,
                                    reason,
                                )
                                if include_diagnostics:
                                    diagnostics.append(
                                        {
                                            "dataset": dataset_name,
                                            "source_system_id": str(source_system_id),
                                            "target_system_id": str(target_system_id),
                                            "reason": reason,
                                            "guardrail": "incremental_base_requirement",
                                            "source_midnight_snapshot_count": len(source_names),
                                            "target_midnight_snapshot_count": len(target_names),
                                        }
                                    )
                                continue

                        # GUARDRAIL 2: Validate starting snapshot exists on source
                        if starting_snapshot:
                            if not validate_snapshot_exists(
                                snapshot_name=starting_snapshot,
                                pool=source_pool,
                                dataset=dataset_name,
                                system_id=source_system_id,
                                snapshot_repo=self.snapshot_repo,
                                comparison_service=self.comparison_service,
                            ):
                                reason = f"starting snapshot {starting_snapshot} does not exist on source system"
                                logger.info(
                                    "GUARDRAIL 3: %s for %s/%s, skipping sync",
                                    reason,
                                    source_pool,
                                    dataset_name,
                                )
                                if include_diagnostics:
                                    diagnostics.append(
                                        {
                                            "dataset": dataset_name,
                                            "source_system_id": str(source_system_id),
                                            "target_system_id": str(target_system_id),
                                            "reason": reason,
                                            "guardrail": "starting_snapshot_validation",
                                            "starting_snapshot": starting_snapshot,
                                        }
                                    )
                                continue

                        # Find ending snapshot (latest missing midnight snapshot on source)
                        source_snapshots = all_snapshots_by_system[source_system_id]
                        source_snapshot_names = {
                            self.comparison_service._extract_snapshot_name(s.name): s.timestamp
                            for s in source_snapshots
                            if is_midnight_snapshot(
                                self.comparison_service._extract_snapshot_name(s.name)
                            )
                        }

                        # Get missing snapshots that exist on source, sorted by timestamp
                        available_missing = [
                            (name, source_snapshot_names[name])
                            for name in missing_snapshots
                            if name in source_snapshot_names
                        ]
                        available_missing.sort(key=lambda x: x[1], reverse=True)

                        if not available_missing:
                            logger.info(
                                "Skipping %s from source %s to target %s: no missing midnight snapshots available on source",
                                dataset_name,
                                source_system_id,
                                target_system_id,
                            )
                            continue

                        ending_snapshot = available_missing[0][0]

                        # GUARDRAIL 3: Validate ending snapshot exists on source
                        if not validate_snapshot_exists(
                            snapshot_name=ending_snapshot,
                            pool=source_pool,
                            dataset=dataset_name,
                            system_id=source_system_id,
                            snapshot_repo=self.snapshot_repo,
                            comparison_service=self.comparison_service,
                        ):
                            reason = (
                                f"ending snapshot {ending_snapshot} does not exist on source system"
                            )
                            logger.info(
                                "GUARDRAIL 4: %s for %s/%s, skipping sync",
                                reason,
                                source_pool,
                                dataset_name,
                            )
                            if include_diagnostics:
                                diagnostics.append(
                                    {
                                        "dataset": dataset_name,
                                        "source_system_id": str(source_system_id),
                                        "target_system_id": str(target_system_id),
                                        "reason": reason,
                                        "guardrail": "ending_snapshot_validation",
                                        "ending_snapshot": ending_snapshot,
                                    }
                                )
                            continue

                        # GUARDRAIL 4: Ensure starting snapshot is older than ending snapshot
                        if starting_snapshot:
                            starting_timestamp = source_snapshot_names.get(starting_snapshot)
                            ending_timestamp = source_snapshot_names.get(ending_snapshot)

                            if starting_timestamp and ending_timestamp:
                                if starting_timestamp >= ending_timestamp:
                                    reason = f"starting snapshot {starting_snapshot} is not older than ending snapshot {ending_snapshot}"
                                    logger.info(
                                        "GUARDRAIL 5: %s, skipping sync",
                                        reason,
                                    )
                                    if include_diagnostics:
                                        diagnostics.append(
                                            {
                                                "dataset": dataset_name,
                                                "source_system_id": str(source_system_id),
                                                "target_system_id": str(target_system_id),
                                                "reason": reason,
                                                "guardrail": "snapshot_ordering_validation",
                                                "starting_snapshot": starting_snapshot,
                                                "ending_snapshot": ending_snapshot,
                                            }
                                        )
                                    continue

                        # GUARDRAIL 5: Validate minimum 24-hour gap between starting and ending snapshots
                        if starting_snapshot:
                            if not validate_snapshot_gap(
                                starting_snapshot=starting_snapshot,
                                ending_snapshot=ending_snapshot,
                                source_snapshot_names=source_snapshot_names,
                                min_gap_hours=self.MIN_SNAPSHOT_GAP_HOURS,
                            ):
                                reason = f"snapshot gap less than {self.MIN_SNAPSHOT_GAP_HOURS} hours between {starting_snapshot} and {ending_snapshot}"
                                logger.info(
                                    "GUARDRAIL 6: Skipping %s from source %s to target %s (%s)",
                                    dataset_name,
                                    source_system_id,
                                    target_system_id,
                                    reason,
                                )
                                if include_diagnostics:
                                    diagnostics.append(
                                        {
                                            "dataset": dataset_name,
                                            "source_system_id": str(source_system_id),
                                            "target_system_id": str(target_system_id),
                                            "reason": reason,
                                            "guardrail": "snapshot_gap_validation",
                                            "min_gap_hours": self.MIN_SNAPSHOT_GAP_HOURS,
                                            "starting_snapshot": starting_snapshot,
                                            "ending_snapshot": ending_snapshot,
                                        }
                                    )
                                continue

                        # Get source and target systems for SSH details
                        source_system = self.system_repo.get(source_system_id)
                        target_system = self.system_repo.get(target_system_id)

                        if not source_system or not target_system:
                            logger.info(
                                "GUARDRAIL 7: Source or target system not found for dataset %s",
                                dataset_name,
                            )
                            continue

                        if not target_system.ssh_hostname:
                            reason = (
                                f"target system {target_system_id} has no SSH hostname configured"
                            )
                            logger.info(
                                "GUARDRAIL 8: %s, skipping sync instruction for dataset %s",
                                reason,
                                dataset_name,
                            )
                            if include_diagnostics:
                                diagnostics.append(
                                    {
                                        "dataset": dataset_name,
                                        "source_system_id": str(source_system_id),
                                        "target_system_id": str(target_system_id),
                                        "reason": reason,
                                        "guardrail": "ssh_configuration",
                                    }
                                )
                            continue

                        # Update sync state to 'syncing' for the target dataset
                        self.update_sync_state(
                            sync_group_id=sync_group_id,
                            dataset=dataset_name,
                            system_id=target_system_id,
                            status=SyncStatus.SYNCING,
                        )

                        # Create dataset instruction for SOURCE system
                        # This tells the source: "send these snapshots to this target"
                        dataset_instruction = {
                            "pool": source_pool,  # Source pool (where snapshots are)
                            "dataset": dataset_name,
                            "target_pool": target_pool,  # Target pool (where to send)
                            "target_dataset": dataset_name,
                            "starting_snapshot": starting_snapshot,
                            "ending_snapshot": ending_snapshot,
                            "source_ssh_hostname": source_system.ssh_hostname,  # Source's own hostname (for reference)
                            "target_ssh_hostname": target_system.ssh_hostname,  # Target's hostname (where to send)
                            "sync_group_id": str(sync_group_id),
                        }

                        dataset_instructions.append(dataset_instruction)

            except (ValueError, KeyError, AttributeError) as e:
                logger.error(
                    "Error processing dataset %s in sync group %s: %s",
                    dataset_name,
                    sync_group_id,
                    e,
                    exc_info=True,
                )

        result = {
            "datasets": dataset_instructions,
            "dataset_count": len(dataset_instructions),
        }

        if include_diagnostics:
            result["diagnostics"] = diagnostics

        return result
