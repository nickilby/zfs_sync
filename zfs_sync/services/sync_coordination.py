"""Service for coordinating snapshot synchronization across systems."""

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set, Tuple
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

        # Get all datasets that should be synced (grouped by dataset name, ignoring pool)
        dataset_mappings = self._get_datasets_for_systems(system_ids)

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
                                    all_snapshots_by_system[sid], key=lambda s: s.timestamp
                                ).name,
                                "timestamp": max(
                                    all_snapshots_by_system[sid], key=lambda s: s.timestamp
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
                                "priority": self._calculate_priority(
                                    missing_snapshot, comparison_dict
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
        logger.info(f"Determining sync actions for sync group {sync_group_id}")

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
                logger.warning(f"Source system {source_system_id} not found, skipping action")
                continue

            # Find snapshot_id from source system
            snapshot_id = self._find_snapshot_id(
                pool=mismatch["pool"],
                dataset=mismatch["dataset"],
                snapshot_name=mismatch["missing_snapshot"],
                system_id=source_system_id,
            )

            # Check if incremental send is possible
            # Use target_pool if available (from pool-agnostic mismatch detection)
            target_pool = mismatch.get("target_pool", mismatch["pool"])
            incremental_base = self._find_incremental_base_by_dataset_name(
                dataset_name=mismatch["dataset"],
                target_system_id=target_system_id,
                target_pool=target_pool,
                source_system_id=source_system_id,
                source_pool=mismatch["pool"],
            )
            is_incremental = incremental_base is not None

            # Filter out full syncs if incremental_only is True
            if incremental_only and not is_incremental:
                logger.debug(
                    f"Skipping full sync for {mismatch['pool']}/{mismatch['dataset']}@{mismatch['missing_snapshot']} "
                    f"(incremental_only=True)"
                )
                continue

            # Generate sync command if SSH details are available
            sync_command = None
            if source_system.ssh_hostname:
                try:
                    if is_incremental and incremental_base:
                        sync_command = SSHCommandGenerator.generate_incremental_sync_command(
                            pool=mismatch["pool"],
                            dataset=mismatch["dataset"],
                            snapshot_name=mismatch["missing_snapshot"],
                            incremental_base=incremental_base,
                            ssh_hostname=source_system.ssh_hostname,
                            ssh_user=source_system.ssh_user,
                            ssh_port=source_system.ssh_port,
                        )
                    else:
                        sync_command = SSHCommandGenerator.generate_full_sync_command(
                            pool=mismatch["pool"],
                            dataset=mismatch["dataset"],
                            snapshot_name=mismatch["missing_snapshot"],
                            ssh_hostname=source_system.ssh_hostname,
                            ssh_user=source_system.ssh_user,
                            ssh_port=source_system.ssh_port,
                        )
                except Exception as e:
                    logger.warning(f"Failed to generate sync command: {e}")

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
        self, system_id: UUID, sync_group_id: Optional[UUID] = None
    ) -> Dict[str, Any]:
        """
        Get sync instructions for a system.

        Returns dataset-grouped instructions for what snapshots need to be synced.
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

        all_datasets = []
        for group in sync_groups:
            if group:
                dataset_result = self.generate_dataset_sync_instructions(
                    sync_group_id=group.id, system_id=system_id, incremental_only=True
                )
                all_datasets.extend(dataset_result.get("datasets", []))

        return {
            "system_id": str(system_id),
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "datasets": all_datasets,
            "dataset_count": len(all_datasets),
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
            "last_updated": max((s.last_check for s in sync_states if s.last_check), default=None),
        }

    def _get_datasets_for_systems(
        self, system_ids: List[UUID]
    ) -> Dict[str, List[Tuple[str, UUID]]]:
        """
        Get unique dataset names with their pool/system mappings.

        Returns a dictionary mapping dataset name to list of (pool, system_id) tuples.
        This allows comparing snapshots across systems with different pool names.
        """
        dataset_mappings: Dict[str, List[Tuple[str, UUID]]] = {}
        for system_id in system_ids:
            snapshots = self.snapshot_repo.get_by_system(system_id)
            for snapshot in snapshots:
                dataset_name = snapshot.dataset
                if dataset_name not in dataset_mappings:
                    dataset_mappings[dataset_name] = []
                # Add (pool, system_id) if not already present
                pool_system = (snapshot.pool, system_id)
                if pool_system not in dataset_mappings[dataset_name]:
                    dataset_mappings[dataset_name].append(pool_system)
        return dataset_mappings

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

    def _find_systems_with_snapshot_by_dataset_name(
        self, dataset_name: str, snapshot_name: str, system_ids: List[UUID]
    ) -> List[Tuple[UUID, str]]:
        """
        Find which systems have a specific snapshot by dataset name (pool-agnostic).

        Returns list of (system_id, pool) tuples for systems that have the snapshot.
        """
        systems_with_snapshot = []
        for system_id in system_ids:
            # Get all snapshots for this system
            all_snapshots = self.snapshot_repo.get_by_system(system_id)
            # Filter by dataset name (ignoring pool)
            for snapshot in all_snapshots:
                if snapshot.dataset == dataset_name:
                    if (
                        self.comparison_service._extract_snapshot_name(snapshot.name)
                        == snapshot_name
                    ):
                        systems_with_snapshot.append((system_id, snapshot.pool))
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
            latest_snapshot_name = self.comparison_service._extract_snapshot_name(
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

    def _find_incremental_base(
        self,
        pool: str,
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
        target_snapshots = self.snapshot_repo.get_by_pool_dataset(
            pool=pool, dataset=dataset, system_id=target_system_id
        )
        source_snapshots = self.snapshot_repo.get_by_pool_dataset(
            pool=pool, dataset=dataset, system_id=source_system_id
        )

        # Extract snapshot names (without pool/dataset prefix)
        target_names = {
            self.comparison_service._extract_snapshot_name(s.name): s.timestamp
            for s in target_snapshots
        }
        source_names = {
            self.comparison_service._extract_snapshot_name(s.name): s.timestamp
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

    def _find_incremental_base_by_dataset_name(
        self,
        dataset_name: str,
        target_system_id: UUID,
        target_pool: str,
        source_system_id: UUID,
        source_pool: str,
    ) -> Optional[str]:
        """
        Find a common base snapshot for incremental send by dataset name (pool-agnostic).

        Returns the snapshot name that exists on both systems and can serve as base,
        or None if no common base is found (full send required).
        """
        # Get all snapshots from both systems using their respective pools
        target_snapshots = self.snapshot_repo.get_by_pool_dataset(
            pool=target_pool, dataset=dataset_name, system_id=target_system_id
        )
        source_snapshots = self.snapshot_repo.get_by_pool_dataset(
            pool=source_pool, dataset=dataset_name, system_id=source_system_id
        )

        # Extract snapshot names (without pool/dataset prefix)
        target_names = {
            self.comparison_service._extract_snapshot_name(s.name): s.timestamp
            for s in target_snapshots
        }
        source_names = {
            self.comparison_service._extract_snapshot_name(s.name): s.timestamp
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

    def generate_dataset_sync_instructions(
        self,
        sync_group_id: UUID,
        system_id: Optional[UUID] = None,
        incremental_only: bool = True,
    ) -> Dict[str, Any]:
        """
        Generate dataset-grouped sync instructions for a sync group or specific system.

        Groups missing snapshots by dataset and returns simplified format with
        starting and ending snapshots for incremental range sends.

        Returns a dictionary with dataset-grouped instructions.
        """
        logger.info(
            f"Generating dataset sync instructions for sync group {sync_group_id}, "
            f"system_id={system_id}, incremental_only={incremental_only}"
        )

        sync_group = self.sync_group_repo.get(sync_group_id)
        if not sync_group:
            raise ValueError(f"Sync group '{sync_group_id}' not found")

        if not sync_group.enabled:
            logger.info(f"Sync group {sync_group_id} is disabled")
            return {"datasets": [], "dataset_count": 0}

        # Get all systems in the sync group
        system_ids = [assoc.system_id for assoc in sync_group.system_associations]

        if len(system_ids) < 2:
            logger.warning(f"Sync group {sync_group_id} has less than 2 systems")
            return {"datasets": [], "dataset_count": 0}

        # Filter to target system if specified
        if system_id:
            if system_id not in system_ids:
                logger.warning(f"System {system_id} is not in sync group {sync_group_id}")
                return {"datasets": [], "dataset_count": 0}
            target_system_ids = [system_id]
        else:
            target_system_ids = system_ids

        # Get all datasets that should be synced (grouped by dataset name, ignoring pool)
        dataset_mappings = self._get_datasets_for_systems(system_ids)

        dataset_instructions = []

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

                # Extract snapshot names (normalized) for comparison
                system_snapshot_names: Dict[UUID, Set[str]] = {}
                for system_id, snapshots in all_snapshots_by_system.items():
                    names = {
                        self.comparison_service._extract_snapshot_name(s.name) for s in snapshots
                    }
                    system_snapshot_names[system_id] = names

                if not system_snapshot_names:
                    continue

                # Find all unique snapshot names across all systems
                all_snapshot_names = (
                    set.union(*system_snapshot_names.values()) if system_snapshot_names else set()
                )

                # Process each target system
                for target_system_id in target_system_ids:
                    if target_system_id not in system_snapshot_names:
                        continue

                    target_names = system_snapshot_names[target_system_id]
                    missing_snapshots = sorted(list(all_snapshot_names - target_names))

                    if not missing_snapshots:
                        continue

                    # Find source system (use first system that has the missing snapshots)
                    source_system_id = None
                    source_pool = None
                    for sid in system_ids:
                        if sid == target_system_id:
                            continue
                        if sid not in system_snapshot_names:
                            continue
                        source_names = system_snapshot_names[sid]
                        if any(name in source_names for name in missing_snapshots):
                            source_system_id = sid
                            source_pool = pool_by_system[sid]
                            break

                    if not source_system_id or not source_pool:
                        logger.warning(
                            f"No source system found for missing snapshots in dataset {dataset_name} "
                            f"for target system {target_system_id}"
                        )
                        continue

                    target_pool = pool_by_system[target_system_id]

                    # Find starting snapshot (most recent common snapshot)
                    starting_snapshot = self._find_incremental_base_by_dataset_name(
                        dataset_name=dataset_name,
                        target_system_id=target_system_id,
                        target_pool=target_pool,
                        source_system_id=source_system_id,
                        source_pool=source_pool,
                    )

                    if incremental_only and not starting_snapshot:
                        logger.debug(
                            f"Skipping {dataset_name} for system {target_system_id} "
                            f"(no common base snapshot, incremental_only=True)"
                        )
                        continue

                    # Find ending snapshot (latest missing snapshot on source)
                    source_snapshots = all_snapshots_by_system[source_system_id]
                    source_snapshot_names = {
                        self.comparison_service._extract_snapshot_name(s.name): s.timestamp
                        for s in source_snapshots
                    }

                    # Get missing snapshots that exist on source, sorted by timestamp
                    available_missing = [
                        (name, source_snapshot_names[name])
                        for name in missing_snapshots
                        if name in source_snapshot_names
                    ]
                    available_missing.sort(key=lambda x: x[1], reverse=True)

                    if not available_missing:
                        continue

                    ending_snapshot = available_missing[0][0]

                    # Get source and target systems for SSH details
                    source_system = self.system_repo.get(source_system_id)
                    target_system = self.system_repo.get(target_system_id)

                    if not source_system or not target_system:
                        logger.warning(
                            f"Source or target system not found for dataset {dataset_name}"
                        )
                        continue

                    # Update sync states to 'syncing' for all missing snapshots
                    for missing_snap in missing_snapshots:
                        snapshot_id = self._find_snapshot_id(
                            pool=source_pool,
                            dataset=dataset_name,
                            snapshot_name=missing_snap,
                            system_id=source_system_id,
                        )
                        if snapshot_id:
                            self.update_sync_state(
                                sync_group_id=sync_group_id,
                                snapshot_id=snapshot_id,
                                system_id=target_system_id,
                                status=SyncStatus.SYNCING,
                            )

                    # Create dataset instruction
                    dataset_instruction = {
                        "pool": source_pool,  # Source pool
                        "dataset": dataset_name,
                        "target_pool": target_pool,  # Target pool
                        "target_dataset": dataset_name,
                        "starting_snapshot": starting_snapshot,
                        "ending_snapshot": ending_snapshot,
                        "source_ssh_hostname": source_system.ssh_hostname,
                        "target_ssh_hostname": target_system.ssh_hostname,
                        "sync_group_id": str(sync_group_id),
                    }

                    dataset_instructions.append(dataset_instruction)

            except Exception as e:
                logger.error(
                    f"Error processing dataset {dataset_name} in sync group {sync_group_id}: {e}",
                    exc_info=True,
                )

        return {
            "datasets": dataset_instructions,
            "dataset_count": len(dataset_instructions),
        }
