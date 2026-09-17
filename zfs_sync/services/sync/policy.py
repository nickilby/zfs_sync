"""Pure send-window policy for snapshot synchronisation.

This module answers one question, with no database, no clock and no logging:

    given what the source and target each hold, and what time it is,
    which snapshots may we send?

Keeping it pure is the point. The previous implementation spread the same rules
across ``sync_coordination.py`` (an inline ``hours_behind <= 72.0``) and
``sync_validators.py`` (``is_snapshot_out_of_sync_by_72h``,
``get_latest_allowed_snapshot_before_now``, ``validate_snapshot_gap``), and the
functions that had unit tests were not the ones the service called. The rules
live here once, and the caller supplies the time.

Snapshots are plain ``(name, timestamp)`` pairs so that nothing in this module
needs an ORM row.
"""

import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import List, Optional, Sequence, Tuple

# A snapshot as this module sees it: its name, and when it was taken.
Snapshot = Tuple[str, datetime]


class DeclineReason(str, Enum):
    """Why a pair produced no incremental send, in machine-readable form.

    These are returned rather than logged. A caller can put them straight into
    an API response, which is what makes "nothing to sync" explainable instead
    of indistinguishable from "everything is fine".
    """

    #: The target already holds everything up to the allowed end.
    IN_SYNC_WITHIN_WINDOW = "in_sync_within_window"
    #: Every source snapshot is newer than the minimum-age cutoff.
    NO_ELIGIBLE_ENDING_SNAPSHOT = "no_eligible_ending_snapshot"
    #: No snapshot exists on both sides, so a full send is required.
    NO_COMMON_BASE = "no_common_base"
    #: The latest common snapshot is the end itself -- nothing to send.
    BASE_EQUALS_END = "base_equals_end"
    #: The target is ahead of the allowed end. Sending would reverse the stream.
    BASE_NEWER_THAN_END = "base_newer_than_end"
    #: The source reported no snapshots for this dataset at all.
    NO_SOURCE_SNAPSHOTS = "no_source_snapshots"
    #: The target holds snapshots the source does not.
    TARGET_DIVERGED = "target_diverged"


def normalize_to_utc(value: datetime) -> datetime:
    """Return ``value`` as a timezone-aware UTC datetime.

    Naive datetimes are assumed to be UTC. Snapshot timestamps reach this
    module from several places -- SQLite (which does not preserve tzinfo),
    PostgreSQL, and client payloads -- so comparing them without normalising
    first raises ``TypeError`` on the mixed case.
    """
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


@dataclass(frozen=True)
class SnapshotNaming:
    """Which snapshot names may anchor a send window.

    The previous implementation hardcoded ``name.endswith("-000000")``. That is
    a site-specific convention: any deployment not taking a midnight snapshot
    got no sync detection at all, silently, and znapzend -- which names
    snapshots ``%Y-%m-%d-%H%M%S`` throughout the day -- would have been almost
    entirely ignored. The convention is configuration instead.
    """

    pattern: str

    def __post_init__(self) -> None:
        # Compile eagerly so a bad pattern fails where it is configured rather
        # than halfway through a sync run.
        try:
            compiled = re.compile(self.pattern)
        except re.error as exc:
            raise ValueError(f"Invalid snapshot naming pattern {self.pattern!r}: {exc}") from exc
        object.__setattr__(self, "_compiled", compiled)

    def is_anchor(self, name: str) -> bool:
        """True when ``name`` may be used as the end of a send window."""
        return self._compiled.search(name) is not None  # type: ignore[attr-defined]


#: The legacy Zengenti convention, kept as a named default rather than a literal.
MIDNIGHT_NAMING = SnapshotNaming(pattern=r"-000000$")


def naming_from_pattern(pattern: Optional[str]) -> Optional[SnapshotNaming]:
    """Build a naming policy from configuration.

    An empty or absent pattern means "accept any snapshot name", which is
    represented as ``None`` so that callers have one thing to pass through.
    """
    if not pattern:
        return None
    return SnapshotNaming(pattern=pattern)


@dataclass(frozen=True)
class SendWindow:
    """The snapshots a sync should send.

    ``base is None`` (equivalently ``full_send``) means there is no common
    snapshot to send from, so the whole dataset must be transferred.
    """

    end: str
    end_timestamp: datetime
    base: Optional[str] = None
    base_timestamp: Optional[datetime] = None

    @property
    def full_send(self) -> bool:
        return self.base is None


@dataclass(frozen=True)
class WindowResult:
    """Outcome of a policy evaluation.

    ``reason`` is populated whenever there is something to explain -- including
    the ``NO_COMMON_BASE`` case, where a window *is* returned but the caller
    should know why it is a full send rather than an incremental one.
    """

    window: Optional[SendWindow] = None
    reason: Optional[DeclineReason] = None

    @property
    def ok(self) -> bool:
        """True when there is something to send."""
        return self.window is not None


def _normalized(snapshots: Sequence[Snapshot]) -> List[Snapshot]:
    return [(name, normalize_to_utc(timestamp)) for name, timestamp in snapshots]


def latest_anchor(
    snapshots: Sequence[Snapshot], naming: Optional[SnapshotNaming]
) -> Optional[Snapshot]:
    """Return the newest snapshot eligible under ``naming``, or ``None``.

    With ``naming=None`` every snapshot is eligible. Ordering is by timestamp,
    never by name: the previous implementation compared snapshot names with
    ``>`` and conceded in a comment that "lexical compare may suffice due to
    timestamp naming", which only holds for one naming convention.
    """
    candidates = [
        (name, timestamp)
        for name, timestamp in _normalized(snapshots)
        if naming is None or naming.is_anchor(name)
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda item: item[1])


def has_diverged(source: Sequence[Snapshot], target: Sequence[Snapshot]) -> bool:
    """True when the target holds snapshots the source does not.

    Such snapshots block an incremental receive without a rollback, so the
    caller usually wants to surface this rather than emit a command that will
    fail on the wire.
    """
    source_names = {name for name, _ in source}
    return any(name not in source_names for name, _ in target)


def choose_send_window(
    source: Sequence[Snapshot],
    target: Sequence[Snapshot],
    now: datetime,
    min_age_hours: float,
    min_gap_hours: float,
    naming: Optional[SnapshotNaming] = None,
) -> WindowResult:
    """Decide which snapshots to send from ``source`` to ``target``.

    The rules, in order:

    1. The end is the newest source snapshot at least ``min_age_hours`` old.
       This is the documented policy: a target that syncs successfully then
       trails the source by at most that much, however far behind it started.
    2. The base is the newest snapshot held by both sides. ``zfs send -I``
       requires it to exist on both, and to be older than the end.
    3. The pair is only worth syncing if base and end are at least
       ``min_gap_hours`` apart.

    Args:
        source: ``(name, timestamp)`` pairs held by the sending system.
        target: ``(name, timestamp)`` pairs held by the receiving system.
        now: Reference time. Injected so this function stays pure.
        min_age_hours: How old a snapshot must be to be sendable.
        min_gap_hours: Minimum base-to-end span worth syncing.
        naming: Restricts which names may end a window. ``None`` accepts any.

    Returns:
        A :class:`WindowResult` carrying either a window or a reason, and
        sometimes both.
    """
    if not source:
        return WindowResult(reason=DeclineReason.NO_SOURCE_SNAPSHOTS)

    reference = normalize_to_utc(now)
    cutoff = reference - timedelta(hours=min_age_hours)

    source_snapshots = _normalized(source)
    target_snapshots = _normalized(target)

    # --- 1. The end: newest source snapshot old enough to send. ---
    eligible = [
        (name, timestamp)
        for name, timestamp in source_snapshots
        if timestamp <= cutoff and (naming is None or naming.is_anchor(name))
    ]
    if not eligible:
        return WindowResult(reason=DeclineReason.NO_ELIGIBLE_ENDING_SNAPSHOT)

    end_name, end_timestamp = max(eligible, key=lambda item: item[1])

    # --- 2. The base: newest snapshot both sides hold. ---
    target_names = {name for name, _ in target_snapshots}
    common = [(name, ts) for name, ts in source_snapshots if name in target_names]

    if not common:
        # Nothing shared, so the target cannot receive an incremental stream.
        # This is still a sendable window, just a full one.
        return WindowResult(
            window=SendWindow(end=end_name, end_timestamp=end_timestamp),
            reason=DeclineReason.NO_COMMON_BASE,
        )

    base_name, base_timestamp = max(common, key=lambda item: item[1])

    if base_name == end_name:
        return WindowResult(reason=DeclineReason.BASE_EQUALS_END)

    if base_timestamp > end_timestamp:
        # The target is already past the allowed end. Sending from here would
        # mean `zfs send -I <newer> <older>` -- reversed and invalid. The old
        # planner emitted exactly that, because it chose the base from all
        # common snapshots while restricting the end to midnight ones.
        return WindowResult(reason=DeclineReason.BASE_NEWER_THAN_END)

    # --- 3. Is the span worth sending? ---
    gap_hours = (end_timestamp - base_timestamp).total_seconds() / 3600
    if gap_hours < min_gap_hours:
        return WindowResult(reason=DeclineReason.IN_SYNC_WITHIN_WINDOW)

    return WindowResult(
        window=SendWindow(
            end=end_name,
            end_timestamp=end_timestamp,
            base=base_name,
            base_timestamp=base_timestamp,
        )
    )
