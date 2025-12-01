"""Query helpers for finding snapshots and datasets."""

from typing import Dict, List, Optional, Tuple
from uuid import UUID
from zfs_sync.database.repositories import SnapshotRepository
from zfs_sync.logging_config import get_logger
from zfs_sync.services.snapshot_comparison import SnapshotComparisonService
from zfs_sync.services.sync_validators import is_midnight_snapshot

logger = get_logger(__name__)


def get_datasets_for_systems(
    system_ids: List[UUID], snapshot_repo: SnapshotRepository
) -> Dict[str, List[Tuple[str, UUID]]]:
    """
    Get unique dataset names with their pool/system mappings.

    Returns a dictionary mapping dataset name to list of (pool, system_id) tuples.
    This allows comparing snapshots across systems with different pool names.

    Args:
        system_ids: List of system IDs to query
        snapshot_repo: SnapshotRepository instance

    Returns:
        Dictionary mapping dataset name to list of (pool, system_id) tuples
    """
    dataset_mappings: Dict[str, List[Tuple[str, UUID]]] = {}
    for system_id in system_ids:
        snapshots = snapshot_repo.get_by_system(system_id)
        for snapshot in snapshots:
            # SQLAlchemy attributes are Column[str] at type-check time but str at runtime
            dataset_name: str = str(snapshot.dataset)  # type: ignore
            if dataset_name not in dataset_mappings:  # type: ignore
                dataset_mappings[dataset_name] = []  # type: ignore
            # Add (pool, system_id) if not already present
            pool_system: Tuple[str, UUID] = (str(snapshot.pool), system_id)  # type: ignore
            if pool_system not in dataset_mappings[dataset_name]:  # type: ignore
                dataset_mappings[dataset_name].append(pool_system)  # type: ignore
    return dataset_mappings


def find_systems_with_snapshot(
    pool: str,
    dataset: str,
    snapshot_name: str,
    system_ids: List[UUID],
    snapshot_repo: SnapshotRepository,
    comparison_service: SnapshotComparisonService,
) -> List[UUID]:
    """Find which systems have a specific snapshot."""
    systems_with_snapshot = []
    for system_id in system_ids:
        snapshots = snapshot_repo.get_by_pool_dataset(
            pool=pool, dataset=dataset, system_id=system_id
        )
        for snapshot in snapshots:
            if comparison_service._extract_snapshot_name(snapshot.name) == snapshot_name:
                systems_with_snapshot.append(system_id)
                break
    return systems_with_snapshot


def find_systems_with_snapshot_by_dataset_name(
    dataset_name: str,
    snapshot_name: str,
    system_ids: List[UUID],
    snapshot_repo: SnapshotRepository,
    comparison_service: SnapshotComparisonService,
) -> List[Tuple[UUID, str]]:
    """
    Find which systems have a specific snapshot by dataset name (pool-agnostic).

    Returns list of (system_id, pool) tuples for systems that have the snapshot.

    Args:
        dataset_name: Dataset name (pool-agnostic)
        snapshot_name: Snapshot name to find
        system_ids: List of system IDs to check
        snapshot_repo: SnapshotRepository instance
        comparison_service: SnapshotComparisonService instance

    Returns:
        List of (system_id, pool) tuples
    """
    systems_with_snapshot = []
    for system_id in system_ids:
        # Get all snapshots for this system
        all_snapshots = snapshot_repo.get_by_system(system_id)
        # Filter by dataset name (ignoring pool)
        for snapshot in all_snapshots:
            if snapshot.dataset == dataset_name:
                if comparison_service._extract_snapshot_name(snapshot.name) == snapshot_name:
                    systems_with_snapshot.append((system_id, snapshot.pool))
                    break
    return systems_with_snapshot


def find_snapshot_id(
    pool: str,
    dataset: str,
    snapshot_name: str,
    system_id: UUID,
    snapshot_repo: SnapshotRepository,
    comparison_service: SnapshotComparisonService,
) -> Optional[UUID]:
    """
    Find snapshot_id for a given snapshot name on a system.

    Returns the snapshot ID if found, None otherwise.

    Args:
        pool: Pool name
        dataset: Dataset name
        snapshot_name: Snapshot name to find
        system_id: System ID
        snapshot_repo: SnapshotRepository instance
        comparison_service: SnapshotComparisonService instance

    Returns:
        Snapshot ID if found, None otherwise
    """
    snapshots = snapshot_repo.get_by_pool_dataset(pool=pool, dataset=dataset, system_id=system_id)
    for snapshot in snapshots:
        if comparison_service._extract_snapshot_name(snapshot.name) == snapshot_name:
            return snapshot.id
    logger.warning(
        "Could not find snapshot_id for %s on system %s for %s/%s",
        snapshot_name,
        system_id,
        pool,
        dataset,
    )
    return None


def estimate_snapshot_size(
    pool: str,
    dataset: str,
    snapshot_name: str,
    source_system_id: UUID,
    snapshot_repo: SnapshotRepository,
    comparison_service: SnapshotComparisonService,
) -> Optional[int]:
    """
    Estimate the size of a snapshot for transfer planning.

    Args:
        pool: Pool name
        dataset: Dataset name
        snapshot_name: Snapshot name
        source_system_id: Source system ID
        snapshot_repo: SnapshotRepository instance
        comparison_service: SnapshotComparisonService instance

    Returns:
        Snapshot size in bytes if found, None otherwise
    """
    snapshots = snapshot_repo.get_by_pool_dataset(
        pool=pool, dataset=dataset, system_id=source_system_id
    )
    for snapshot in snapshots:
        if comparison_service._extract_snapshot_name(snapshot.name) == snapshot_name:
            return snapshot.size
    return None


def find_incremental_base(
    pool: str,
    dataset: str,
    target_system_id: UUID,
    source_system_id: UUID,
    snapshot_repo: SnapshotRepository,
    comparison_service: SnapshotComparisonService,
) -> Optional[str]:
    """
    Find a common base snapshot for incremental send.

    Returns the snapshot name that exists on both systems and can serve as base,
    or None if no common base is found (full send required).

    Args:
        pool: Pool name
        dataset: Dataset name
        target_system_id: Target system ID
        source_system_id: Source system ID
        snapshot_repo: SnapshotRepository instance
        comparison_service: SnapshotComparisonService instance

    Returns:
        Snapshot name if found, None otherwise
    """
    # Get all snapshots from both systems
    target_snapshots = snapshot_repo.get_by_pool_dataset(
        pool=pool, dataset=dataset, system_id=target_system_id
    )
    source_snapshots = snapshot_repo.get_by_pool_dataset(
        pool=pool, dataset=dataset, system_id=source_system_id
    )

    # Extract snapshot names (without pool/dataset prefix)
    target_names = {
        comparison_service._extract_snapshot_name(s.name): s.timestamp for s in target_snapshots
    }
    source_names = {
        comparison_service._extract_snapshot_name(s.name): s.timestamp for s in source_snapshots
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


def find_incremental_base_by_dataset_name(
    dataset_name: str,
    target_system_id: UUID,
    target_pool: str,
    source_system_id: UUID,
    source_pool: str,
    snapshot_repo: SnapshotRepository,
    comparison_service: SnapshotComparisonService,
) -> Optional[str]:
    """
    Find a common base snapshot for incremental send by dataset name (pool-agnostic).
    Only returns midnight snapshots.

    Returns the snapshot name that exists on both systems and can serve as base,
    or None if no common base is found (full send required).

    Args:
        dataset_name: Dataset name (pool-agnostic)
        target_system_id: Target system ID
        target_pool: Target pool name
        source_system_id: Source system ID
        source_pool: Source pool name
        snapshot_repo: SnapshotRepository instance
        comparison_service: SnapshotComparisonService instance

    Returns:
        Snapshot name if found, None otherwise
    """
    # Get all snapshots from both systems using their respective pools
    target_snapshots = snapshot_repo.get_by_pool_dataset(
        pool=target_pool, dataset=dataset_name, system_id=target_system_id
    )
    source_snapshots = snapshot_repo.get_by_pool_dataset(
        pool=source_pool, dataset=dataset_name, system_id=source_system_id
    )

    # Extract snapshot names (without pool/dataset prefix) - only midnight snapshots
    target_names = {
        comparison_service._extract_snapshot_name(s.name): s.timestamp
        for s in target_snapshots
        if is_midnight_snapshot(comparison_service._extract_snapshot_name(s.name))
    }
    source_names = {
        comparison_service._extract_snapshot_name(s.name): s.timestamp
        for s in source_snapshots
        if is_midnight_snapshot(comparison_service._extract_snapshot_name(s.name))
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


def calculate_priority(
    snapshot_name: str, comparison: Dict, comparison_service: SnapshotComparisonService
) -> int:
    """
    Calculate priority for syncing a snapshot.

    Higher priority = more important to sync.

    Args:
        snapshot_name: Snapshot name
        comparison: Comparison dictionary with latest_snapshots and missing_snapshots
        comparison_service: SnapshotComparisonService instance

    Returns:
        Priority score (higher = more important)
    """
    priority = 10  # Base priority

    # If it's the latest snapshot, increase priority
    latest_snapshots = comparison.get("latest_snapshots", {})
    for latest_info in latest_snapshots.values():
        # Extract snapshot name from full name (e.g., "tank/data@snapshot-20240115" -> "snapshot-20240115")
        latest_snapshot_name = comparison_service._extract_snapshot_name(
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
