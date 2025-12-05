"""Validation helpers for sync coordination."""

from datetime import datetime, timedelta, timezone
from typing import Dict, Iterable, List, Optional, Set, Tuple

from zfs_sync.database.models import SnapshotModel
from zfs_sync.logging_config import get_logger
from zfs_sync.services.snapshot_comparison import SnapshotComparisonService

logger = get_logger(__name__)

# Minimum time gap between starting and ending snapshots (72 hours)
MIN_SNAPSHOT_GAP_HOURS = 72


def normalize_to_utc(dt: datetime) -> datetime:
    """
    Normalize a datetime to UTC, converting naive datetimes to UTC.

    Args:
        dt: Datetime object (may be naive or timezone-aware)

    Returns:
        Timezone-aware datetime in UTC
    """
    if dt.tzinfo is None:
        # Naive datetime - assume UTC
        return dt.replace(tzinfo=timezone.utc)
    # Already timezone-aware - convert to UTC
    return dt.astimezone(timezone.utc)


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


def is_snapshot_out_of_sync_by_hours(
    source_snapshots: List[SnapshotModel],
    target_snapshots: List[SnapshotModel],
    source_snapshot_names: Set[str],
    target_snapshot_names: Set[str],
    comparison_service: SnapshotComparisonService,
    threshold_hours: float,
) -> bool:
    """
    Check if datasets are more than the specified threshold hours out of sync.

    Args:
        source_snapshots: List of snapshots from source system
        target_snapshots: List of snapshots from target system
        source_snapshot_names: Set of normalized snapshot names from source (already filtered to midnight snapshots)
        target_snapshot_names: Set of normalized snapshot names from target (already filtered to midnight snapshots)
        comparison_service: SnapshotComparisonService instance for extracting snapshot names
        threshold_hours: Number of hours threshold for considering systems out of sync

    Returns:
        True if datasets are more than threshold_hours out of sync, False otherwise
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

    # Get dataset name from snapshots (all snapshots should have the same dataset)
    dataset_name = source_snapshots[0].dataset if source_snapshots else "unknown"

    # Check if target has this snapshot
    if latest_source_name in target_snapshot_names:
        # Target has the latest source snapshot - this is the expected "in sync" state
        # Log as INFO since this is successful/expected behavior, not a warning
        logger.info(
            "[72h_check] Dataset '%s': Target has the latest source midnight snapshot %s (%s). "
            "Systems are in sync based on latest midnight snapshots.",
            dataset_name,
            latest_source_name,
            normalize_to_utc(latest_source.timestamp).isoformat(),
        )
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
        latest_source_timestamp_utc = normalize_to_utc(latest_source.timestamp)
        age_hours: float = (now - latest_source_timestamp_utc).total_seconds() / 3600
        result: bool = age_hours > threshold_hours
        return result

    latest_target = max(target_midnight_snapshots, key=lambda s: s.timestamp)  # type: ignore[arg-type,return-value]

    # Calculate the time difference between latest source and latest target
    latest_source_timestamp_utc = normalize_to_utc(latest_source.timestamp)
    latest_target_timestamp_utc = normalize_to_utc(latest_target.timestamp)
    time_diff = latest_source_timestamp_utc - latest_target_timestamp_utc
    hours_diff: float = time_diff.total_seconds() / 3600

    latest_target_name = comparison_service.extract_snapshot_name(latest_target.name)

    # Check if target's latest snapshot exists on source (to detect orphaned snapshots)
    target_latest_exists_on_source = latest_target_name in source_snapshot_names

    # Log the comparison for debugging
    logger.debug(
        "Sync check: source latest=%s (%s), target latest=%s (%s), diff=%.2f hours, "
        "target_latest_exists_on_source=%s",
        latest_source_name,
        latest_source_timestamp_utc.isoformat(),
        latest_target_name,
        latest_target_timestamp_utc.isoformat(),
        hours_diff,
        target_latest_exists_on_source,
    )

    # If target's latest snapshot doesn't exist on source, it might be an orphaned snapshot
    if not target_latest_exists_on_source:
        logger.warning(
            "[72h_check] Dataset '%s': Target's latest midnight snapshot %s (%s) does not exist on source. "
            "This may be an orphaned snapshot. Source latest: %s (%s), diff=%.2f hours",
            dataset_name,
            latest_target_name,
            latest_target_timestamp_utc.isoformat(),
            latest_source_name,
            latest_source_timestamp_utc.isoformat(),
            hours_diff,
        )

    # If source is ahead by more than threshold hours, systems are out of sync
    result = hours_diff > threshold_hours
    logger.warning(
        "[72h_check] Dataset '%s': Sync check result: %s (hours_diff=%.2f > %.2f=%s). "
        "Source latest: %s (%s), Target latest: %s (%s)",
        dataset_name,
        result,
        hours_diff,
        threshold_hours,
        hours_diff > threshold_hours,
        latest_source_name,
        latest_source_timestamp_utc.isoformat(),
        latest_target_name,
        latest_target_timestamp_utc.isoformat(),
    )
    return result


def is_snapshot_out_of_sync_by_24h(
    source_snapshots: List[SnapshotModel],
    target_snapshots: List[SnapshotModel],
    source_snapshot_names: Set[str],
    target_snapshot_names: Set[str],
    comparison_service: SnapshotComparisonService,
) -> bool:
    """
    Check if datasets are more than 24 hours out of sync.

    Convenience wrapper for is_snapshot_out_of_sync_by_hours with threshold_hours=24.0.

    Args:
        source_snapshots: List of snapshots from source system
        target_snapshots: List of snapshots from target system
        source_snapshot_names: Set of normalized snapshot names from source (already filtered to midnight snapshots)
        target_snapshot_names: Set of normalized snapshot names from target (already filtered to midnight snapshots)
        comparison_service: SnapshotComparisonService instance for extracting snapshot names

    Returns:
        True if datasets are more than 24 hours out of sync, False otherwise
    """
    return is_snapshot_out_of_sync_by_hours(
        source_snapshots=source_snapshots,
        target_snapshots=target_snapshots,
        source_snapshot_names=source_snapshot_names,
        target_snapshot_names=target_snapshot_names,
        comparison_service=comparison_service,
        threshold_hours=24.0,
    )


def is_snapshot_out_of_sync_by_72h(
    source_snapshots: List[SnapshotModel],
    target_snapshots: List[SnapshotModel],
    source_snapshot_names: Set[str],
    target_snapshot_names: Set[str],
    comparison_service: SnapshotComparisonService,
) -> bool:
    """
    Check if datasets are more than 72 hours out of sync.

    Convenience wrapper for is_snapshot_out_of_sync_by_hours with threshold_hours=72.0.

    Args:
        source_snapshots: List of snapshots from source system
        target_snapshots: List of snapshots from target system
        source_snapshot_names: Set of normalized snapshot names from source (already filtered to midnight snapshots)
        target_snapshot_names: Set of normalized snapshot names from target (already filtered to midnight snapshots)
        comparison_service: SnapshotComparisonService instance for extracting snapshot names

    Returns:
        True if datasets are more than 72 hours out of sync, False otherwise
    """
    return is_snapshot_out_of_sync_by_hours(
        source_snapshots=source_snapshots,
        target_snapshots=target_snapshots,
        source_snapshot_names=source_snapshot_names,
        target_snapshot_names=target_snapshot_names,
        comparison_service=comparison_service,
        threshold_hours=72.0,
    )


def get_latest_allowed_snapshot_before_now(
    snapshots: Iterable[Tuple[str, datetime]],
    now: Optional[datetime] = None,
    min_age_hours: float = float(MIN_SNAPSHOT_GAP_HOURS),
) -> Optional[str]:
    """
    Return the latest snapshot name whose timestamp is at least ``min_age_hours``
    older than ``now``.

    This is used to implement the policy:
    - Only send snapshots whose timestamps are at least 72 hours older than "now"
      (so the target always lags source by at most ~72 hours).

    Args:
        snapshots: Iterable of (snapshot_name, timestamp) pairs for the source.
        now: Reference time (defaults to datetime.now(timezone.utc)).
        min_age_hours: Minimum age in hours a snapshot must have to be eligible.

    Returns:
        The latest eligible snapshot name, or None if none are old enough.
    """
    if now is None:
        now = datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)

    cutoff = now - timedelta(hours=min_age_hours)

    eligible: List[Tuple[str, datetime]] = []
    snapshot_list = list(snapshots)
    for name, ts in snapshot_list:
        ts_utc = normalize_to_utc(ts)
        if ts_utc <= cutoff:
            eligible.append((name, ts_utc))

    if not eligible:
        logger.warning(
            "[72h_check] get_latest_allowed_snapshot_before_now: No eligible snapshots found. "
            "Total snapshots: %d, cutoff: %s (now=%s - %f hours), "
            "latest snapshot timestamp: %s",
            len(snapshot_list),
            cutoff.isoformat(),
            now.isoformat(),
            min_age_hours,
            max((normalize_to_utc(ts) for _, ts in snapshot_list), default=None),
        )
        return None

    # Return the latest-by-timestamp eligible snapshot
    eligible.sort(key=lambda item: item[1])
    result = eligible[-1][0]
    logger.debug(
        "[72h_check] get_latest_allowed_snapshot_before_now: Returning %s (from %d eligible out of %d total)",
        result,
        len(eligible),
        len(snapshot_list),
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
        min_gap_hours: Minimum gap in hours (default: 72)

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

    # Calculate time difference (normalize both timestamps to UTC)
    starting_timestamp_utc = normalize_to_utc(starting_timestamp)
    ending_timestamp_utc = normalize_to_utc(ending_timestamp)
    time_diff = ending_timestamp_utc - starting_timestamp_utc
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
