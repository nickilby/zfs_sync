"""Characterization of the legacy planner's multi-target behaviour.

Recorded before the planner is replaced, so that the rewrite's behavioural
differences are reviewed rather than discovered in production.

The scenario is the one the fleet actually runs: one hub, several spokes, the
same dataset lagging on more than one of them. It is the case
``get_sync_instructions`` consolidates on ``dataset`` alone, which silently
drops every target after the first.
"""

from datetime import datetime, timedelta, timezone

import pytest

from zfs_sync.database.repositories import (
    SnapshotRepository,
    SyncGroupRepository,
    SystemRepository,
)
from zfs_sync.services.sync_coordination import SyncCoordinationService

DATASET = "DATA1"


def _snapshot_name(day: int) -> str:
    return f"2025-01-{day:02d}-000000"


def _timestamp(day: int) -> datetime:
    return datetime(2025, 1, day, 0, 0, 0, tzinfo=timezone.utc)


@pytest.fixture
def fan_out(test_db):
    """One hub and two spokes, both far behind on the same dataset.

    The hub holds 2025-01-01 through 2025-01-20. Each spoke stopped at
    2025-01-02, so both are ~18 days behind -- comfortably outside any
    72-hour window, and both genuinely need syncing.
    """
    systems = SystemRepository(test_db)
    groups = SyncGroupRepository(test_db)
    snapshots = SnapshotRepository(test_db)

    hub = systems.create(
        hostname="hub1",
        platform="linux",
        connectivity_status="online",
        ssh_hostname="hub1-san",
    )
    spoke_a = systems.create(
        hostname="spoke1",
        platform="linux",
        connectivity_status="online",
        ssh_hostname="spoke1-san",
    )
    spoke_b = systems.create(
        hostname="spoke2",
        platform="linux",
        connectivity_status="online",
        ssh_hostname="spoke2-san",
    )

    group = groups.create(
        name="fan-out-group",
        description="One hub, two lagging spokes",
        directional=True,
        hub_system_id=hub.id,
    )
    for system in (hub, spoke_a, spoke_b):
        groups.add_system(group.id, system.id)

    # Hub: a full run of daily snapshots.
    for day in range(1, 21):
        snapshots.create(
            name=f"hubpool1/{DATASET}@{_snapshot_name(day)}",
            pool="hubpool1",
            dataset=DATASET,
            timestamp=_timestamp(day),
            size=1024,
            system_id=hub.id,
        )

    # Each spoke stopped early, on its own pool.
    for spoke, pool in ((spoke_a, "spokepool1"), (spoke_b, "spokepool2")):
        for day in (1, 2):
            snapshots.create(
                name=f"{pool}/{DATASET}@{_snapshot_name(day)}",
                pool=pool,
                dataset=DATASET,
                timestamp=_timestamp(day),
                size=1024,
                system_id=spoke.id,
            )

    return {"group": group, "hub": hub, "spokes": [spoke_a, spoke_b], "db": test_db}


class TestLegacyMultiTargetBehaviour:
    def test_both_targets_are_detected_as_behind(self, fan_out):
        """Detection is not where the loss happens -- both spokes are found."""
        service = SyncCoordinationService(fan_out["db"])

        mismatches = service.detect_sync_mismatches(sync_group_id=fan_out["group"].id)

        targets = {m["target_system_id"] for m in mismatches}
        assert targets == {str(spoke.id) for spoke in fan_out["spokes"]}

    def test_both_targets_produce_actions(self, fan_out):
        """Action generation also keeps both targets."""
        service = SyncCoordinationService(fan_out["db"])

        actions = service.determine_sync_actions(sync_group_id=fan_out["group"].id)

        targets = {a["target_system_id"] for a in actions}
        assert targets == {str(spoke.id) for spoke in fan_out["spokes"]}

    def test_consolidation_collapses_two_targets_into_one_instruction(self, fan_out):
        """The defect.

        `get_sync_instructions` keys `consolidated` on dataset alone, so the
        second target's entry overwrites nothing and is simply dropped: two
        systems needing the same dataset yield one instruction, naming one
        target. The other spoke is never told to sync and nothing reports it.
        """
        service = SyncCoordinationService(fan_out["db"])

        instructions = service.get_sync_instructions(system_id=fan_out["hub"].id)

        datasets = instructions["datasets"]
        assert len(datasets) == 1, "characterizing: one dataset entry, not one per target"

        named_targets = {entry.get("target_ssh_hostname") for entry in datasets}
        assert len(named_targets) == 1, "characterizing: only one target survives"

        # Both spokes need a sync, but only one of them is addressed.
        all_spoke_hosts = {"spoke1-san", "spoke2-san"}
        assert named_targets < all_spoke_hosts, (
            "characterizing the bug: at least one target is silently dropped. "
            f"addressed={named_targets}, needing sync={all_spoke_hosts}"
        )

    def test_the_dropped_targets_command_only_reaches_a_host_that_cannot_run_it(
        self, fan_out
    ):
        """Why the collapse matters operationally.

        Every generated command sends *from* the hub's pool, so only the hub
        can execute it. Asking as each spoke does produce that spoke's own
        instruction -- but it is handed to a machine where `hubpool1` does not
        exist, so running it fails.

        The net effect: the one host able to perform these sends is told about
        a single target, and the second target's command exists only in a
        response delivered to a host that cannot use it.
        """
        service = SyncCoordinationService(fan_out["db"])
        hub_pool = "hubpool1"

        hub_view = service.get_sync_instructions(system_id=fan_out["hub"].id)
        hub_targets = {e.get("target_ssh_hostname") for e in hub_view["datasets"]}
        assert len(hub_targets) == 1, "the executing host sees only one target"

        # The spoke that the hub never heard about.
        dropped = ({"spoke1-san", "spoke2-san"} - hub_targets).pop()

        for spoke in fan_out["spokes"]:
            result = service.get_sync_instructions(system_id=spoke.id)
            for entry in result["datasets"]:
                if entry.get("target_ssh_hostname") != dropped:
                    continue
                # The instruction exists, but it sends from the hub's pool.
                assert entry["pool"] == hub_pool
                assert all(
                    command.startswith(f"zfs send -c -I {hub_pool}/")
                    for command in entry.get("commands", [])
                ), "characterizing: the command is only executable on the hub"


class TestLegacyWindowSelection:
    """What the legacy code picks as the ending snapshot.

    The documented policy is "the latest source snapshot at least 72h old".
    The code sends the hub's latest snapshot outright, with no age cap.
    """

    def test_ending_snapshot_is_the_hubs_latest_not_the_72h_cap(self, fan_out):
        service = SyncCoordinationService(fan_out["db"])

        instructions = service.get_sync_instructions(system_id=fan_out["hub"].id)
        entry = instructions["datasets"][0]

        assert entry["ending_snapshot"] == _snapshot_name(20), (
            "characterizing: the hub's newest snapshot is sent regardless of age"
        )

    def test_nothing_reports_why_anything_was_suppressed(self, fan_out):
        """Diagnostics are empty even when asked for, on the happy path."""
        service = SyncCoordinationService(fan_out["db"])

        instructions = service.get_sync_instructions(
            system_id=fan_out["hub"].id, include_diagnostics=True
        )

        assert instructions.get("diagnostics") == [], (
            "characterizing: no per-pair reasoning is reported"
        )


class TestLegacyInSyncReporting:
    """What a caller sees when everything is fine."""

    def test_an_in_sync_fleet_is_indistinguishable_from_a_broken_one(self, test_db):
        systems = SystemRepository(test_db)
        groups = SyncGroupRepository(test_db)
        snapshots = SnapshotRepository(test_db)

        hub = systems.create(
            hostname="hub1", platform="linux", ssh_hostname="hub1-san", connectivity_status="online"
        )
        spoke = systems.create(
            hostname="spoke1",
            platform="linux",
            ssh_hostname="spoke1-san",
            connectivity_status="online",
        )
        group = groups.create(name="in-sync-group", directional=True, hub_system_id=hub.id)
        groups.add_system(group.id, hub.id)
        groups.add_system(group.id, spoke.id)

        recent = datetime.now(timezone.utc) - timedelta(days=1)
        for system, pool in ((hub, "hubpool1"), (spoke, "spokepool1")):
            snapshots.create(
                name=f"{pool}/{DATASET}@2025-01-01-000000",
                pool=pool,
                dataset=DATASET,
                timestamp=recent,
                size=1024,
                system_id=system.id,
            )

        service = SyncCoordinationService(test_db)
        result = service.get_sync_instructions(system_id=hub.id, include_diagnostics=True)

        assert result["datasets"] == []
        assert result["dataset_count"] == 0
        # The reason there is nothing to do is not reported anywhere in the
        # response -- a healthy fleet and a totally suppressed one look alike.
        assert all(
            "in sync" not in str(entry.get("message", "")).lower()
            for entry in result.get("diagnostics", [])
        )
