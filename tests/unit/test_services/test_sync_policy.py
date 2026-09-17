"""Unit tests for the pure sync policy.

These tests define the send-window rules the project has documented but never
actually run: ``docs/MISMATCH_FILTERING_ANALYSIS.md`` describes a "now - 72h"
policy implemented by ``get_latest_allowed_snapshot_before_now()``, a function
that exists and is imported by nothing. The policy lives here instead, as pure
functions over ``(name, timestamp)`` pairs, so what is tested is what runs.

Everything here is clock-injected -- no test reads the real time.
"""

from datetime import datetime, timedelta, timezone

import pytest

from zfs_sync.services.sync.policy import (
    MIDNIGHT_NAMING,
    DeclineReason,
    SnapshotNaming,
    choose_send_window,
    has_diverged,
    latest_anchor,
    naming_from_pattern,
    normalize_to_utc,
)

NAME_FORMAT = "%Y-%m-%d-%H%M%S"


def snap(name: str):
    """Build a (name, timestamp) pair from the YYYY-MM-DD-HHMMSS convention."""
    return name, datetime.strptime(name, NAME_FORMAT).replace(tzinfo=timezone.utc)


def snaps(*names: str):
    return [snap(name) for name in names]


def at(text: str) -> datetime:
    return datetime.fromisoformat(text)


class TestDocumentedSendWindow:
    """The worked example from docs/MISMATCH_FILTERING_ANALYSIS.md.

    Source holds twice-daily snapshots; the target last shares 2025-10-30.
    At 2025-12-04T09:13:30Z with a 72h minimum age the cutoff is
    2025-12-01T09:13:30Z, so 2025-12-01-000000 is allowed as the end and
    2025-12-01-120000 is not.
    """

    SOURCE = snaps(
        "2025-10-30-000000",
        "2025-11-30-000000",
        "2025-12-01-000000",
        "2025-12-01-120000",
        "2025-12-02-000000",
        "2025-12-02-120000",
        "2025-12-03-000000",
        "2025-12-03-120000",
    )
    TARGET = snaps("2025-10-29-000000", "2025-10-30-000000")
    NOW = at("2025-12-04T09:13:30+00:00")

    def test_picks_the_documented_base_and_end(self):
        result = choose_send_window(
            source=self.SOURCE,
            target=self.TARGET,
            now=self.NOW,
            min_age_hours=72.0,
            min_gap_hours=72.0,
        )

        assert result.ok
        assert result.window.base == "2025-10-30-000000"
        assert result.window.end == "2025-12-01-000000"
        assert result.window.full_send is False

    def test_does_not_select_a_snapshot_newer_than_the_cutoff(self):
        result = choose_send_window(
            source=self.SOURCE,
            target=self.TARGET,
            now=self.NOW,
            min_age_hours=72.0,
            min_gap_hours=72.0,
        )

        assert result.window.end != "2025-12-01-120000"
        assert result.window.end_timestamp <= self.NOW - timedelta(hours=72)


class TestEndSelection:
    def test_target_already_holds_everything_up_to_the_cutoff(self):
        source = snaps("2025-01-01-000000", "2025-01-10-000000")
        target = snaps("2025-01-01-000000", "2025-01-10-000000")

        result = choose_send_window(
            source=source,
            target=target,
            now=at("2025-01-20T00:00:00+00:00"),
            min_age_hours=72.0,
            min_gap_hours=72.0,
        )

        assert not result.ok
        assert result.reason is DeclineReason.BASE_EQUALS_END

    def test_every_source_snapshot_is_too_new(self):
        source = snaps("2025-01-20-000000", "2025-01-20-120000")

        result = choose_send_window(
            source=source,
            target=snaps("2025-01-01-000000"),
            now=at("2025-01-21T00:00:00+00:00"),
            min_age_hours=72.0,
            min_gap_hours=72.0,
        )

        assert not result.ok
        assert result.reason is DeclineReason.NO_ELIGIBLE_ENDING_SNAPSHOT

    def test_a_smaller_minimum_age_allows_a_later_end(self):
        # At now=Jan 21, a 72h minimum age puts the cutoff at Jan 18 (so the
        # Jan 20 snapshot is too new), while a 12h age puts it at Jan 20 12:00
        # (so the Jan 20 00:00 snapshot qualifies).
        source = snaps("2025-01-01-000000", "2025-01-17-000000", "2025-01-20-000000")
        target = snaps("2025-01-01-000000")
        now = at("2025-01-21T00:00:00+00:00")

        strict = choose_send_window(
            source=source, target=target, now=now, min_age_hours=72.0, min_gap_hours=1.0
        )
        relaxed = choose_send_window(
            source=source, target=target, now=now, min_age_hours=12.0, min_gap_hours=1.0
        )

        assert strict.window.end == "2025-01-17-000000"
        assert relaxed.window.end == "2025-01-20-000000"

    def test_no_source_snapshots_at_all(self):
        result = choose_send_window(
            source=[],
            target=snaps("2025-01-01-000000"),
            now=at("2025-01-20T00:00:00+00:00"),
            min_age_hours=72.0,
            min_gap_hours=72.0,
        )

        assert not result.ok
        assert result.reason is DeclineReason.NO_SOURCE_SNAPSHOTS


class TestBaseSelection:
    def test_no_common_snapshot_requires_a_full_send(self):
        result = choose_send_window(
            source=snaps("2025-01-01-000000", "2025-01-10-000000"),
            target=snaps("2024-06-01-000000"),
            now=at("2025-01-20T00:00:00+00:00"),
            min_age_hours=72.0,
            min_gap_hours=72.0,
        )

        assert result.ok
        assert result.window.full_send is True
        assert result.window.base is None
        assert result.window.end == "2025-01-10-000000"
        assert result.reason is DeclineReason.NO_COMMON_BASE

    def test_empty_target_requires_a_full_send(self):
        result = choose_send_window(
            source=snaps("2025-01-01-000000", "2025-01-10-000000"),
            target=[],
            now=at("2025-01-20T00:00:00+00:00"),
            min_age_hours=72.0,
            min_gap_hours=72.0,
        )

        assert result.ok
        assert result.window.full_send is True
        assert result.reason is DeclineReason.NO_COMMON_BASE

    def test_both_sides_empty(self):
        result = choose_send_window(
            source=[],
            target=[],
            now=at("2025-01-20T00:00:00+00:00"),
            min_age_hours=72.0,
            min_gap_hours=72.0,
        )

        assert not result.ok
        assert result.reason is DeclineReason.NO_SOURCE_SNAPSHOTS

    def test_base_newer_than_end_is_not_a_reversed_send(self):
        """The bug this rule exists to prevent.

        The legacy planner chose the incremental base from *all* common
        snapshots while restricting the end to midnight snapshots, so a target
        holding a newer non-midnight snapshot that also existed on the source
        produced `zfs send -I <newer> <older>` -- reversed and invalid.
        """
        source = snaps(
            "2025-01-01-000000",
            "2025-01-10-000000",
            "2025-01-19-120000",
        )
        target = snaps("2025-01-01-000000", "2025-01-19-120000")

        result = choose_send_window(
            source=source,
            target=target,
            now=at("2025-01-20T00:00:00+00:00"),
            min_age_hours=72.0,
            min_gap_hours=1.0,
            naming=MIDNIGHT_NAMING,
        )

        assert not result.ok
        assert result.reason is DeclineReason.BASE_NEWER_THAN_END

    def test_base_is_the_latest_common_snapshot_older_than_the_end(self):
        source = snaps(
            "2025-01-01-000000",
            "2025-01-05-000000",
            "2025-01-08-000000",
            "2025-01-10-000000",
        )
        target = snaps("2025-01-01-000000", "2025-01-05-000000")

        result = choose_send_window(
            source=source,
            target=target,
            now=at("2025-01-20T00:00:00+00:00"),
            min_age_hours=72.0,
            min_gap_hours=1.0,
        )

        assert result.window.base == "2025-01-05-000000"
        assert result.window.end == "2025-01-10-000000"


class TestMinimumGap:
    """The gap rule decides whether a pair is worth syncing at all."""

    SOURCE = snaps("2025-01-01-000000", "2025-01-04-000000")
    TARGET = snaps("2025-01-01-000000")
    NOW = at("2025-02-01T00:00:00+00:00")

    def test_exactly_the_minimum_gap_is_accepted(self):
        """72.0h apart must sync.

        The `>` versus `>=` ambiguity at this boundary is named as a root cause
        in docs/MISMATCH_FILTERING_ANALYSIS.md, so it is pinned explicitly.
        """
        result = choose_send_window(
            source=self.SOURCE,
            target=self.TARGET,
            now=self.NOW,
            min_age_hours=72.0,
            min_gap_hours=72.0,
        )

        assert result.ok, "a gap of exactly min_gap_hours must be syncable"
        assert result.window.base == "2025-01-01-000000"
        assert result.window.end == "2025-01-04-000000"

    def test_just_under_the_minimum_gap_is_declined(self):
        result = choose_send_window(
            source=snaps("2025-01-01-000000", "2025-01-03-230000"),
            target=self.TARGET,
            now=self.NOW,
            min_age_hours=72.0,
            min_gap_hours=72.0,
        )

        assert not result.ok
        assert result.reason is DeclineReason.IN_SYNC_WITHIN_WINDOW

    def test_the_gap_threshold_is_configurable(self):
        result = choose_send_window(
            source=snaps("2025-01-01-000000", "2025-01-02-000000"),
            target=self.TARGET,
            now=self.NOW,
            min_age_hours=72.0,
            min_gap_hours=12.0,
        )

        assert result.ok
        assert result.window.end == "2025-01-02-000000"


class TestSnapshotNaming:
    """Naming is configuration, not a hardcoded Zengenti convention.

    `is_midnight_snapshot` hardcoded `name.endswith("-000000")`, so any site not
    using that convention got zero sync detection, silently -- and znapzend,
    which names snapshots %Y-%m-%d-%H%M%S but not only at midnight, would be
    almost entirely ignored.
    """

    SOURCE = snaps(
        "2025-01-01-000000",
        "2025-01-10-000000",
        "2025-01-10-060000",
        "2025-01-10-120000",
    )
    TARGET = snaps("2025-01-01-000000")
    NOW = at("2025-02-01T00:00:00+00:00")

    def test_without_a_naming_policy_any_snapshot_may_end_the_window(self):
        result = choose_send_window(
            source=self.SOURCE,
            target=self.TARGET,
            now=self.NOW,
            min_age_hours=72.0,
            min_gap_hours=1.0,
        )

        assert result.window.end == "2025-01-10-120000"

    def test_the_midnight_policy_restricts_ends_to_midnight_snapshots(self):
        result = choose_send_window(
            source=self.SOURCE,
            target=self.TARGET,
            now=self.NOW,
            min_age_hours=72.0,
            min_gap_hours=1.0,
            naming=MIDNIGHT_NAMING,
        )

        assert result.window.end == "2025-01-10-000000"

    def test_a_znapzend_style_policy_accepts_non_midnight_snapshots(self):
        znapzend = SnapshotNaming(pattern=r"^\d{4}-\d{2}-\d{2}-\d{6}$")

        result = choose_send_window(
            source=self.SOURCE,
            target=self.TARGET,
            now=self.NOW,
            min_age_hours=72.0,
            min_gap_hours=1.0,
            naming=znapzend,
        )

        assert result.window.end == "2025-01-10-120000"

    def test_a_policy_matching_nothing_declines_with_a_clear_reason(self):
        result = choose_send_window(
            source=self.SOURCE,
            target=self.TARGET,
            now=self.NOW,
            min_age_hours=72.0,
            min_gap_hours=1.0,
            naming=SnapshotNaming(pattern=r"^nothing-matches-this$"),
        )

        assert not result.ok
        assert result.reason is DeclineReason.NO_ELIGIBLE_ENDING_SNAPSHOT

    def test_latest_anchor_reports_the_newest_matching_snapshot(self):
        assert latest_anchor(self.SOURCE, MIDNIGHT_NAMING)[0] == "2025-01-10-000000"
        assert latest_anchor(self.SOURCE, None)[0] == "2025-01-10-120000"
        assert latest_anchor([], MIDNIGHT_NAMING) is None

    def test_an_empty_configured_pattern_means_accept_any_name(self):
        """Settings document '' as "accept any"; it must not compile to a
        pattern that matches everything by accident, nor blow up."""
        assert naming_from_pattern("") is None
        assert naming_from_pattern(None) is None

    def test_a_configured_pattern_builds_a_policy(self):
        naming = naming_from_pattern(r"-000000$")
        assert naming is not None
        assert naming.is_anchor("2025-01-01-000000") is True
        assert naming.is_anchor("2025-01-01-120000") is False

    def test_an_invalid_configured_pattern_is_rejected(self):
        with pytest.raises(ValueError):
            naming_from_pattern("([unclosed")

    def test_an_invalid_pattern_is_rejected_when_the_policy_is_built(self):
        with pytest.raises(ValueError):
            SnapshotNaming(pattern="([unclosed")


class TestTimezoneHandling:
    def test_naive_timestamps_are_treated_as_utc(self):
        aware_source = snaps("2025-01-01-000000", "2025-01-10-000000")
        naive_source = [(name, ts.replace(tzinfo=None)) for name, ts in aware_source]
        target = snaps("2025-01-01-000000")
        now = at("2025-01-20T00:00:00+00:00")

        aware = choose_send_window(
            source=aware_source, target=target, now=now, min_age_hours=72.0, min_gap_hours=1.0
        )
        naive = choose_send_window(
            source=naive_source, target=target, now=now, min_age_hours=72.0, min_gap_hours=1.0
        )

        assert aware.window.base == naive.window.base
        assert aware.window.end == naive.window.end

    def test_a_naive_now_is_treated_as_utc(self):
        result = choose_send_window(
            source=snaps("2025-01-01-000000", "2025-01-10-000000"),
            target=snaps("2025-01-01-000000"),
            now=datetime(2025, 1, 20, 0, 0, 0),
            min_age_hours=72.0,
            min_gap_hours=1.0,
        )

        assert result.ok
        assert result.window.end == "2025-01-10-000000"

    def test_a_non_utc_timezone_is_converted_rather_than_truncated(self):
        tokyo = timezone(timedelta(hours=9))
        source = [
            ("a", datetime(2025, 1, 1, 9, 0, tzinfo=tokyo)),
            ("b", datetime(2025, 1, 10, 9, 0, tzinfo=tokyo)),
        ]

        result = choose_send_window(
            source=source,
            target=[("a", datetime(2025, 1, 1, 9, 0, tzinfo=tokyo))],
            now=at("2025-01-20T00:00:00+00:00"),
            min_age_hours=72.0,
            min_gap_hours=1.0,
        )

        assert result.window.end == "b"
        assert result.window.end_timestamp == datetime(2025, 1, 10, 0, 0, tzinfo=timezone.utc)

    def test_normalize_to_utc_is_idempotent(self):
        aware = datetime(2025, 1, 1, tzinfo=timezone.utc)
        assert normalize_to_utc(aware) == aware
        assert normalize_to_utc(datetime(2025, 1, 1)) == aware


class TestDivergence:
    """A target holding snapshots the source lacks cannot receive an
    incremental stream without a rollback, so the planner needs to see it."""

    def test_a_target_subset_has_not_diverged(self):
        source = snaps("2025-01-01-000000", "2025-01-02-000000")
        target = snaps("2025-01-01-000000")

        assert has_diverged(source, target) is False

    def test_a_target_with_its_own_snapshot_has_diverged(self):
        source = snaps("2025-01-01-000000")
        target = snaps("2025-01-01-000000", "2025-01-05-000000")

        assert has_diverged(source, target) is True

    def test_an_empty_target_has_not_diverged(self):
        assert has_diverged(snaps("2025-01-01-000000"), []) is False

    def test_an_empty_source_with_any_target_has_diverged(self):
        assert has_diverged([], snaps("2025-01-01-000000")) is True


class TestPurity:
    """The policy must stay free of I/O so that what is tested is what runs."""

    def test_module_imports_no_database_or_clock(self):
        import inspect

        from zfs_sync.services.sync import policy

        source = inspect.getsource(policy)
        assert "sqlalchemy" not in source
        assert "zfs_sync.database" not in source
        assert "datetime.now(" not in source
        assert "logger" not in source

    def test_inputs_are_not_mutated(self):
        source = snaps("2025-01-01-000000", "2025-01-10-000000")
        target = snaps("2025-01-01-000000")
        source_copy = list(source)
        target_copy = list(target)

        choose_send_window(
            source=source,
            target=target,
            now=at("2025-01-20T00:00:00+00:00"),
            min_age_hours=72.0,
            min_gap_hours=1.0,
        )

        assert source == source_copy
        assert target == target_copy
