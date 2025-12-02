"""Validation helpers for sync coordination."""

from datetime import datetime, timezone
from typing import Dict, List, Optional, Set

from zfs_sync.database.models import SnapshotModel
from zfs_sync.logging_config import get_logger
from zfs_sync.services.snapshot_comparison import SnapshotComparisonService

logger = get_logger(__name__)

# Minimum time gap between starting and ending snapshots (24 hours)
MIN_SNAPSHOT_GAP_HOURS = 24


def is_midnight_snapshot(snapshot_name: str) -> bool:
    """
    Check if a snapshot name represents a midnight snapshot (ends with -000000).

    Args:
        snapshot_name: Snapshot name (e.g., "2025-11-29-000000")

    Returns:
        True if the snapshot is a midnight snapshot, False otherwise
    """
    # Check if snapshot name ends with -000000 (midnight format)
    return snapshot_name.endswith("-000000")


def is_snapshot_out_of_sync_by_24h(
    source_snapshots: List[SnapshotModel],
    target_snapshots: List[SnapshotModel],
    source_snapshot_names: Set[str],
    target_snapshot_names: Set[str],
    comparison_service: SnapshotComparisonService,
) -> bool:
    """
    Check if datasets are more than 24 hours out of sync.

    Args:
        source_snapshots: List of snapshots from source system
        target_snapshots: List of snapshots from target system
        source_snapshot_names: Set of normalized snapshot names from source (already filtered to midnight snapshots)
        target_snapshot_names: Set of normalized snapshot names from target (already filtered to midnight snapshots)
        comparison_service: SnapshotComparisonService instance for extracting snapshot names

    Returns:
        True if datasets are more than 24 hours out of sync, False otherwise
    """
    # Find the latest midnight snapshot on source
    # Note: source_snapshot_names is already filtered to midnight snapshots, so we just need to check is_midnight_snapshot
    source_midnight_snapshots = []
    for s in source_snapshots:
        # pylint: disable=protected-access
        snapshot_name = comparison_service.extract_snapshot_name(s.name)  # type: ignore[attr-defined]
        # source_snapshot_names is already filtered to midnight snapshots, so if it's in the set, it's a midnight snapshot
        if snapshot_name in source_snapshot_names:
            source_midnight_snapshots.append(s)

    if not source_midnight_snapshots:
        return False

    latest_source = max(source_midnight_snapshots, key=lambda s: s.timestamp)
    latest_source_name = comparison_service.extract_snapshot_name(latest_source.name)

    # Check if target has this snapshot
    if latest_source_name in target_snapshot_names:
        # Target has the latest source snapshot, but we should still check if there are missing intermediate snapshots
        # However, for the 24-hour guardrail, if target has the latest, they're considered in sync
        return False  # Target has the latest, so not out of sync

    # Find the latest midnight snapshot on target
    # Note: target_snapshot_names is already filtered to midnight snapshots
    target_midnight_snapshots = []
    for s in target_snapshots:
        # pylint: disable=protected-access
        snapshot_name = comparison_service.extract_snapshot_name(s.name)  # type: ignore[attr-defined]
        # target_snapshot_names is already filtered to midnight snapshots, so if it's in the set, it's a midnight snapshot
        if snapshot_name in target_snapshot_names:
            target_midnight_snapshots.append(s)

    if not target_midnight_snapshots:
        # Target has no midnight snapshots, check age of source's latest
        now = datetime.now(timezone.utc)
        age_hours: float = (now - latest_source.timestamp).total_seconds() / 3600  # type: ignore[operator]
        result: bool = age_hours > 24
        return result

    latest_target = max(target_midnight_snapshots, key=lambda s: s.timestamp)  # type: ignore[arg-type,return-value]

    # Calculate the time difference between latest source and latest target
    time_diff = latest_source.timestamp - latest_target.timestamp  # type: ignore[operator]
    hours_diff: float = time_diff.total_seconds() / 3600

    # Log the comparison for debugging
    logger.debug(
        "Sync check: source latest=%s (%s), target latest=%s (%s), diff=%.2f hours",
        latest_source_name,
        latest_source.timestamp.isoformat(),
        comparison_service.extract_snapshot_name(latest_target.name),
        latest_target.timestamp.isoformat(),
        hours_diff,
    )

    # If source is ahead by more than 24 hours, systems are out of sync
    result = hours_diff > 24
    logger.debug(
        "Sync check result: %s (hours_diff=%.2f > 24=%s)",
        result,
        hours_diff,
        hours_diff > 24,
    )
    return result


def validate_snapshot_exists(
    snapshot_name: str,
    pool: str,
    dataset: str,
    system_id,
    snapshot_repo,
    comparison_service: SnapshotComparisonService,
) -> bool:
    """
    Validate that a snapshot exists in the database for the given system.

    Args:
        snapshot_name: Normalized snapshot name (without pool/dataset prefix)
        pool: Pool name
        dataset: Dataset name
        system_id: System ID
        snapshot_repo: SnapshotRepository instance
        comparison_service: SnapshotComparisonService instance

    Returns:
        True if snapshot exists, False otherwise
    """
    snapshots = snapshot_repo.get_by_pool_dataset(pool=pool, dataset=dataset, system_id=system_id)

    for snapshot in snapshots:
        normalized_name = comparison_service.extract_snapshot_name(snapshot.name)
        if normalized_name == snapshot_name:
            return True

    return False


def validate_snapshot_gap(
    starting_snapshot: Optional[str],
    ending_snapshot: str,
    source_snapshot_names: Dict[str, datetime],
    min_gap_hours: int = MIN_SNAPSHOT_GAP_HOURS,
) -> bool:
    """
    Validate that there is a minimum time gap between starting and ending snapshots.

    Args:
        starting_snapshot: Starting snapshot name (None for full sync)
        ending_snapshot: Ending snapshot name
        source_snapshot_names: Dictionary mapping snapshot names to timestamps
        min_gap_hours: Minimum gap in hours (default: 24)

    Returns:
        True if gap is sufficient or no starting snapshot, False otherwise
    """
    if not starting_snapshot:
        # Full sync, no gap requirement
        return True

    starting_timestamp = source_snapshot_names.get(starting_snapshot)
    ending_timestamp = source_snapshot_names.get(ending_snapshot)

    if not starting_timestamp or not ending_timestamp:
        logger.warning(
            "Cannot validate snapshot gap: missing timestamps for starting=%s, ending=%s",
            starting_snapshot,
            ending_snapshot,
        )
        return False

    # Calculate time difference
    time_diff = ending_timestamp - starting_timestamp
    hours_diff = time_diff.total_seconds() / 3600

    if hours_diff < min_gap_hours:
        logger.debug(
            "Snapshot gap too small: %.2f hours between %s and %s (minimum: %d hours)",
            hours_diff,
            starting_snapshot,
            ending_snapshot,
            min_gap_hours,
        )
        return False

    return True
