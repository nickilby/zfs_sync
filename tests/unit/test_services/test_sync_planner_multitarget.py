"""Multi-target fan-out: the case the previous planner silently lost.

The scenario mirrors tests/unit/test_services/test_sync_multitarget_characterization.py
exactly, so the two modules can be read side by side: that one records what the
legacy coordination service did, this one asserts what the planner does instead.

The legacy behaviour was to consolidate instructions keyed on dataset alone.
Two spokes needing the same dataset collapsed into one instruction naming one
target. Because every command sends from the hub's pool, only the hub can
execute them -- so the one host capable of doing the work was told about a
single target, and the other spoke's command was returned only to a machine
where the hub's pool does not exist.
"""

from datetime import datetime, timezone

import pytest

from zfs_sync.database.repositories import (
    SnapshotRepository,
    SyncGroupRepository,
    SystemRepository,
)
from zfs_sync.services.sync.planner import SyncPlanner
from zfs_sync.services.sync.types import SyncAction

DATASET = "DATA1"
NOW = datetime(2025, 2, 1, tzinfo=timezone.utc)

SPOKES = [
    ("spoke1", "spokepool1"),
    ("spoke2", "spokepool2"),
    ("spoke3", "spokepool3"),
]


def day(number: int) -> datetime:
    return datetime(2025, 1, number, 0, 0, 0, tzinfo=timezone.utc)


def name(number: int) -> str:
    return f"2025-01-{number:02d}-000000"


@pytest.fixture
def fan_out(test_db):
    """One hub and three spokes, all behind on the same dataset.

    Each spoke stopped at a different point, so they need different
    incremental bases -- a single consolidated instruction cannot be correct
    for more than one of them.
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
    for number in range(1, 21):
        snapshots.create(
            name=f"hubpool1/{DATASET}@{name(number)}",
            pool="hubpool1",
            dataset=DATASET,
            timestamp=day(number),
            size=1024,
            system_id=hub.id,
        )

    spokes = {}
    # Each spoke stops at a different day, so each needs a different base.
    for index, ((hostname, pool), stopped_at) in enumerate(zip(SPOKES, [2, 5, 9])):
        spoke = systems.create(
            hostname=hostname,
            platform="linux",
            connectivity_status="online",
            ssh_hostname=f"{hostname}-san",
            ssh_user="backup",
            ssh_port=2222 + index,
        )
        for number in range(1, stopped_at + 1):
            snapshots.create(
                name=f"{pool}/{DATASET}@{name(number)}",
                pool=pool,
                dataset=DATASET,
                timestamp=day(number),
                size=1024,
                system_id=spoke.id,
            )
        spokes[hostname] = {"system": spoke, "pool": pool, "stopped_at": stopped_at}

    group = groups.create(
        name="fan-out-group",
        description="One hub, three lagging spokes",
        directional=True,
        hub_system_id=hub.id,
    )
    groups.add_system(group.id, hub.id)
    for entry in spokes.values():
        groups.add_system(group.id, entry["system"].id)

    return {"db": test_db, "group": group, "hub": hub, "spokes": spokes}


class TestEveryTargetIsPlanned:
    def test_three_targets_produce_three_decisions(self, fan_out):
        plan = SyncPlanner(fan_out["db"]).plan_group(fan_out["group"].id, now=NOW)

        assert len(plan.decisions) == 3
        assert {d.target.hostname for d in plan.decisions} == set(fan_out["spokes"])

    def test_every_target_is_told_to_sync(self, fan_out):
        plan = SyncPlanner(fan_out["db"]).plan_group(fan_out["group"].id, now=NOW)

        assert len(plan.instructions) == 3
        assert all(d.action is SyncAction.SYNC for d in plan.instructions)

    def test_each_target_keeps_its_own_pool_and_ssh_identity(self, fan_out):
        """The fields the legacy consolidation discarded for all but one target."""
        plan = SyncPlanner(fan_out["db"]).plan_group(fan_out["group"].id, now=NOW)

        by_host = {d.target.hostname: d for d in plan.decisions}
        for index, (hostname, pool) in enumerate(SPOKES):
            decision = by_host[hostname]
            assert decision.target_pool == pool
            assert decision.target.ssh_hostname == f"{hostname}-san"
            assert decision.target.ssh_user == "backup"
            assert decision.target.ssh_port == 2222 + index
            assert decision.source_pool == "hubpool1"

    def test_each_target_gets_the_base_that_matches_its_own_state(self, fan_out):
        """The strongest argument against dataset-keyed consolidation.

        The spokes stopped at different days, so a single shared instruction
        could be correct for at most one of them.
        """
        plan = SyncPlanner(fan_out["db"]).plan_group(fan_out["group"].id, now=NOW)

        by_host = {d.target.hostname: d for d in plan.decisions}
        for hostname, entry in fan_out["spokes"].items():
            assert by_host[hostname].starting_snapshot == name(entry["stopped_at"])

        bases = {d.starting_snapshot for d in plan.decisions}
        assert len(bases) == 3, "each target needs its own base"

    def test_all_targets_share_the_same_ending_snapshot(self, fan_out):
        """They differ in where they start, not in where they are going."""
        plan = SyncPlanner(fan_out["db"]).plan_group(fan_out["group"].id, now=NOW)

        assert {d.ending_snapshot for d in plan.decisions} == {name(20)}


class TestTheExecutingHostSeesEverything:
    def test_the_hub_receives_all_three_instructions(self, fan_out):
        """The heart of the fix.

        Only the hub can run these commands. Previously it was told about one
        target; now it receives every pair it is responsible for.
        """
        decisions = SyncPlanner(fan_out["db"]).plan_for_system(fan_out["hub"].id, now=NOW)

        assert len(decisions) == 3
        assert {d.target.ssh_hostname for d in decisions} == {
            "spoke1-san",
            "spoke2-san",
            "spoke3-san",
        }

    def test_no_spoke_is_asked_to_run_a_command_it_cannot(self, fan_out):
        for entry in fan_out["spokes"].values():
            decisions = SyncPlanner(fan_out["db"]).plan_for_system(
                entry["system"].id, now=NOW
            )
            assert decisions == [], "a spoke cannot send from the hub's pool"


class TestMixedOutcomesAcrossTargets:
    def test_an_in_sync_target_does_not_suppress_the_others(self, fan_out):
        """One target being fine must not hide the ones that are not."""
        snapshots = SnapshotRepository(fan_out["db"])
        caught_up = fan_out["spokes"]["spoke1"]
        for number in range(caught_up["stopped_at"] + 1, 21):
            snapshots.create(
                name=f"{caught_up['pool']}/{DATASET}@{name(number)}",
                pool=caught_up["pool"],
                dataset=DATASET,
                timestamp=day(number),
                size=1024,
                system_id=caught_up["system"].id,
            )

        plan = SyncPlanner(fan_out["db"]).plan_group(fan_out["group"].id, now=NOW)

        assert len(plan.decisions) == 3, "every pair is still reported"
        assert len(plan.instructions) == 2
        by_host = {d.target.hostname: d for d in plan.decisions}
        assert by_host["spoke1"].action is SyncAction.SKIP
        assert by_host["spoke2"].action is SyncAction.SYNC
        assert by_host["spoke3"].action is SyncAction.SYNC

    def test_each_declined_target_carries_its_own_reason(self, fan_out):
        """Different targets can be declined for different reasons at once."""
        db = fan_out["db"]
        systems = SystemRepository(db)
        snapshots = SnapshotRepository(db)

        # spoke1 catches up entirely -> nothing left to send.
        caught_up = fan_out["spokes"]["spoke1"]
        for number in range(caught_up["stopped_at"] + 1, 21):
            snapshots.create(
                name=f"{caught_up['pool']}/{DATASET}@{name(number)}",
                pool=caught_up["pool"],
                dataset=DATASET,
                timestamp=day(number),
                size=1024,
                system_id=caught_up["system"].id,
            )

        # spoke2 loses its SSH identity -> nothing can be addressed to it.
        systems.update(fan_out["spokes"]["spoke2"]["system"].id, ssh_hostname=None)

        plan = SyncPlanner(db).plan_group(fan_out["group"].id, now=NOW)

        by_host = {d.target.hostname: d for d in plan.decisions}
        assert by_host["spoke1"].action is SyncAction.SKIP
        assert by_host["spoke2"].reason == "missing_ssh_identity"
        assert by_host["spoke3"].action is SyncAction.SYNC
        # Three distinct outcomes reported from one plan.
        assert len({d.reason for d in plan.decisions}) == 3

    def test_nothing_to_do_is_still_fully_reported(self, fan_out):
        """An entirely in-sync group returns a decision per pair, not silence."""
        snapshots = SnapshotRepository(fan_out["db"])
        for entry in fan_out["spokes"].values():
            for number in range(entry["stopped_at"] + 1, 21):
                snapshots.create(
                    name=f"{entry['pool']}/{DATASET}@{name(number)}",
                    pool=entry["pool"],
                    dataset=DATASET,
                    timestamp=day(number),
                    size=1024,
                    system_id=entry["system"].id,
                )

        plan = SyncPlanner(fan_out["db"]).plan_group(fan_out["group"].id, now=NOW)

        assert plan.instructions == []
        assert len(plan.declined) == 3
        assert all(d.reason for d in plan.declined), "every decline states why"
        assert plan.skipped_reason is None, "the group itself was plannable"
