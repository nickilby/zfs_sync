"""Planning over snapshots that znapzend created and prunes.

znapzend owns snapshot creation and retention on the hosts it manages. Two
things about that matter here.

Its default ``tsformat`` is ``%Y-%m-%d-%H%M%S`` and it takes snapshots
throughout the day. The previous hardcoded midnight convention
(``name.endswith("-000000")``) would have treated all but one snapshot a day as
ineligible, so a perfectly current znapzend host would have looked days behind.

And it prunes. A snapshot chosen as an incremental base can be gone by the time
anything acts on the decision, so the planner must cope with the base
disappearing rather than proposing it again.
"""

from datetime import datetime, timedelta, timezone

from zfs_sync.services.sync.policy import (
    MIDNIGHT_NAMING,
    ZNAPZEND_NAMING,
    DeclineReason,
    choose_send_window,
    latest_anchor,
)

NAME_FORMAT = "%Y-%m-%d-%H%M%S"


def snap(name: str):
    return name, datetime.strptime(name, NAME_FORMAT).replace(tzinfo=timezone.utc)


def snaps(*names: str):
    return [snap(name) for name in names]


def every_six_hours(day: int, hours=(0, 6, 12, 18)):
    """A znapzend plan taking four snapshots a day."""
    return [f"2025-01-{day:02d}-{hour:02d}0000" for hour in hours]


def plan_over(days, hours=(0, 6, 12, 18)):
    return snaps(*[name for day in days for name in every_six_hours(day, hours)])


NOW = datetime(2025, 2, 1, tzinfo=timezone.utc)


class TestNamingConvention:
    def test_the_midnight_convention_ignores_most_znapzend_snapshots(self):
        """What the hardcoded convention would have done to a znapzend host."""
        source = plan_over(range(1, 11))

        with_midnight = latest_anchor(source, MIDNIGHT_NAMING)
        with_znapzend = latest_anchor(source, ZNAPZEND_NAMING)

        assert with_midnight[0] == "2025-01-10-000000"
        assert with_znapzend[0] == "2025-01-10-180000"

    def test_a_znapzend_host_is_planned_to_its_newest_eligible_snapshot(self):
        result = choose_send_window(
            source=plan_over(range(1, 11)),
            target=plan_over([1]),
            now=NOW,
            min_age_hours=72.0,
            min_gap_hours=1.0,
            naming=ZNAPZEND_NAMING,
        )

        assert result.ok
        assert result.window.end == "2025-01-10-180000"
        assert result.window.base == "2025-01-01-180000"

    def test_a_host_taking_only_midnight_snapshots_still_works(self):
        """The pattern is permissive, not a requirement to change schedule."""
        source = snaps(*[f"2025-01-{day:02d}-000000" for day in range(1, 11)])

        result = choose_send_window(
            source=source,
            target=snaps("2025-01-01-000000"),
            now=NOW,
            min_age_hours=72.0,
            min_gap_hours=1.0,
            naming=ZNAPZEND_NAMING,
        )

        assert result.window.end == "2025-01-10-000000"

    def test_snapshots_from_another_tool_are_not_treated_as_anchors(self):
        """A manual or zrepl snapshot must not end a znapzend window."""
        source = plan_over([1, 2]) + snaps("2025-01-03-120000")
        source.append(("manual-before-upgrade", datetime(2025, 1, 4, tzinfo=timezone.utc)))

        assert latest_anchor(source, ZNAPZEND_NAMING)[0] == "2025-01-03-120000"


class TestRetentionPruning:
    """znapzend expires snapshots on its own schedule."""

    def test_pruning_the_base_selects_a_newer_common_snapshot(self):
        """The next plan must not keep proposing a base that is gone."""
        source = plan_over(range(1, 11))
        target_before = plan_over([1, 2])

        before = choose_send_window(
            source=source,
            target=target_before,
            now=NOW,
            min_age_hours=72.0,
            min_gap_hours=1.0,
            naming=ZNAPZEND_NAMING,
        )
        assert before.window.base == "2025-01-02-180000"

        # znapzend expires everything from day 1 on the target.
        target_after = plan_over([2])
        after = choose_send_window(
            source=source,
            target=target_after,
            now=NOW,
            min_age_hours=72.0,
            min_gap_hours=1.0,
            naming=ZNAPZEND_NAMING,
        )

        assert after.window.base == "2025-01-02-180000"
        assert after.window.base in {name for name, _ in target_after}

    def test_pruning_every_common_snapshot_falls_back_to_a_full_send(self):
        source = plan_over(range(5, 11))
        target = plan_over([1])  # retained nothing the source still has

        result = choose_send_window(
            source=source,
            target=target,
            now=NOW,
            min_age_hours=72.0,
            min_gap_hours=1.0,
            naming=ZNAPZEND_NAMING,
        )

        assert result.ok
        assert result.window.full_send is True
        assert result.reason is DeclineReason.NO_COMMON_BASE

    def test_a_source_pruned_back_inside_the_age_window_has_nothing_to_send(self):
        """Aggressive retention can leave nothing old enough to send."""
        recent = [
            (f"2025-02-01-{hour:02d}0000", datetime(2025, 2, 1, hour, tzinfo=timezone.utc))
            for hour in (0, 6, 12, 18)
        ]

        result = choose_send_window(
            source=recent,
            target=[],
            now=datetime(2025, 2, 2, tzinfo=timezone.utc),
            min_age_hours=72.0,
            min_gap_hours=1.0,
            naming=ZNAPZEND_NAMING,
        )

        assert not result.ok
        assert result.reason is DeclineReason.NO_ELIGIBLE_ENDING_SNAPSHOT

    def test_a_target_that_znapzend_replicated_itself_reports_in_sync(self):
        """znapzend can replicate too. Where it already has, there is nothing
        for this service to do, and it should say so rather than duplicating
        the transfer."""
        source = plan_over(range(1, 11))

        result = choose_send_window(
            source=source,
            target=list(source),
            now=NOW,
            min_age_hours=72.0,
            min_gap_hours=1.0,
            naming=ZNAPZEND_NAMING,
        )

        assert not result.ok
        assert result.reason is DeclineReason.BASE_EQUALS_END


class TestFrequentSnapshotSchedules:
    """znapzend plans are often far finer-grained than daily."""

    def test_a_fifteen_minute_plan_still_respects_the_age_cap(self):
        start = datetime(2025, 1, 1, tzinfo=timezone.utc)
        source = [
            (
                (start + timedelta(minutes=15 * i)).strftime(NAME_FORMAT),
                start + timedelta(minutes=15 * i),
            )
            for i in range(0, 400)
        ]
        now = start + timedelta(days=5)

        result = choose_send_window(
            source=source,
            target=[source[0]],
            now=now,
            min_age_hours=72.0,
            min_gap_hours=1.0,
            naming=ZNAPZEND_NAMING,
        )

        assert result.ok
        chosen = dict(source)[result.window.end]
        assert chosen <= now - timedelta(hours=72)

    def test_the_window_covers_every_intermediate_snapshot(self):
        """zfs send -I sends the whole range, so a fine-grained plan does not
        mean one transfer per snapshot."""
        source = plan_over(range(1, 11))

        result = choose_send_window(
            source=source,
            target=plan_over([1]),
            now=NOW,
            min_age_hours=72.0,
            min_gap_hours=1.0,
            naming=ZNAPZEND_NAMING,
        )

        assert result.window.base == "2025-01-01-180000"
        assert result.window.end == "2025-01-10-180000"
