"""Unit tests for the sync planner.

The planner's job is to emit a decision for *every* (dataset, source, target)
pair it considers, so that "nothing to sync" is always explainable. These tests
cover pair enumeration, the group-level skips, and the evidence carried on each
decision. Multi-target fan-out has its own module.
"""

from datetime import datetime, timedelta, timezone

import pytest

from zfs_sync.database.repositories import (
    SnapshotRepository,
    SyncGroupRepository,
    SystemRepository,
)
from zfs_sync.services.sync.planner import SyncPlanner, extract_snapshot_name
from zfs_sync.services.sync.types import (
    PlanReason,
    SyncAction,
    SyncGroupNotFound,
)

DATASET = "DATA1"
NOW = datetime(2025, 2, 1, tzinfo=timezone.utc)


def day(number: int) -> datetime:
    return datetime(2025, 1, number, 0, 0, 0, tzinfo=timezone.utc)


def name(number: int) -> str:
    return f"2025-01-{number:02d}-000000"


class Fleet:
    """Small builder so each test reads as the scenario it describes."""

    def __init__(self, db):
        self.db = db
        self.systems = SystemRepository(db)
        self.groups = SyncGroupRepository(db)
        self.snapshots = SnapshotRepository(db)

    def system(self, hostname, ssh_hostname="unset", **kwargs):
        if ssh_hostname == "unset":
            ssh_hostname = f"{hostname}-san"
        return self.systems.create(
            hostname=hostname,
            platform="linux",
            connectivity_status="online",
            ssh_hostname=ssh_hostname,
            **kwargs,
        )

    def group(self, hub, members, **kwargs):
        options = {"directional": True, "hub_system_id": hub.id, "name": "group"}
        options.update(kwargs)
        group = self.groups.create(**options)
        for member in members:
            self.groups.add_system(group.id, member.id)
        return group

    def snaps(self, system, pool, days, dataset=DATASET):
        for number in days:
            self.snapshots.create(
                name=f"{pool}/{dataset}@{name(number)}",
                pool=pool,
                dataset=dataset,
                timestamp=day(number),
                size=1024,
                system_id=system.id,
            )


@pytest.fixture
def fleet(test_db):
    return Fleet(test_db)


class TestSnapshotNameExtraction:
    def test_strips_the_pool_and_dataset_prefix(self):
        assert extract_snapshot_name("tank/data@2025-01-01-000000") == "2025-01-01-000000"

    def test_a_bare_name_is_returned_unchanged(self):
        assert extract_snapshot_name("2025-01-01-000000") == "2025-01-01-000000"

    def test_only_the_final_at_sign_separates_the_name(self):
        assert extract_snapshot_name("tank/od@d@2025-01-01-000000") == "2025-01-01-000000"


class TestGroupLevelSkips:
    """A group that cannot be planned says so, rather than returning nothing."""

    def test_unknown_group_raises_a_typed_error(self, fleet):
        import uuid

        planner = SyncPlanner(fleet.db)

        with pytest.raises(SyncGroupNotFound):
            planner.plan_group(uuid.uuid4())

    def test_disabled_group(self, fleet):
        hub = fleet.system("hub1")
        spoke = fleet.system("spoke1")
        group = fleet.group(hub, [hub, spoke], name="disabled", enabled=False)

        plan = SyncPlanner(fleet.db).plan_group(group.id, now=NOW)

        assert plan.decisions == []
        assert plan.skipped_reason == PlanReason.GROUP_DISABLED.value

    def test_non_directional_group(self, fleet):
        hub = fleet.system("hub1")
        spoke = fleet.system("spoke1")
        group = fleet.groups.create(name="flat", directional=False)
        fleet.groups.add_system(group.id, hub.id)
        fleet.groups.add_system(group.id, spoke.id)

        plan = SyncPlanner(fleet.db).plan_group(group.id, now=NOW)

        assert plan.skipped_reason == PlanReason.GROUP_NOT_DIRECTIONAL.value

    def test_group_with_a_single_system(self, fleet):
        hub = fleet.system("hub1")
        group = fleet.group(hub, [hub], name="lonely")

        plan = SyncPlanner(fleet.db).plan_group(group.id, now=NOW)

        assert plan.skipped_reason == PlanReason.GROUP_TOO_FEW_SYSTEMS.value

    def test_hub_not_a_member_of_its_own_group(self, fleet):
        hub = fleet.system("hub1")
        spoke_a = fleet.system("spoke1")
        spoke_b = fleet.system("spoke2")
        group = fleet.groups.create(name="orphan-hub", directional=True, hub_system_id=hub.id)
        fleet.groups.add_system(group.id, spoke_a.id)
        fleet.groups.add_system(group.id, spoke_b.id)

        plan = SyncPlanner(fleet.db).plan_group(group.id, now=NOW)

        assert plan.skipped_reason == PlanReason.HUB_NOT_IN_GROUP.value


class TestSinglePair:
    def test_a_lagging_target_is_planned(self, fleet):
        hub = fleet.system("hub1")
        spoke = fleet.system("spoke1")
        group = fleet.group(hub, [hub, spoke], name="simple")
        fleet.snaps(hub, "hubpool1", range(1, 21))
        fleet.snaps(spoke, "spokepool1", [1, 2])

        plan = SyncPlanner(fleet.db).plan_group(group.id, now=NOW)

        assert len(plan.decisions) == 1
        decision = plan.decisions[0]
        assert decision.action is SyncAction.SYNC
        assert decision.dataset == DATASET
        assert decision.source.hostname == "hub1"
        assert decision.target.hostname == "spoke1"
        assert decision.starting_snapshot == name(2)
        assert decision.ending_snapshot == name(20)
        assert decision.source_pool == "hubpool1"
        assert decision.target_pool == "spokepool1"
        assert decision.full_send is False

    def test_evidence_is_carried_even_when_declined(self, fleet):
        hub = fleet.system("hub1")
        spoke = fleet.system("spoke1")
        group = fleet.group(hub, [hub, spoke], name="in-sync")
        fleet.snaps(hub, "hubpool1", range(1, 21))
        fleet.snaps(spoke, "spokepool1", range(1, 21))

        plan = SyncPlanner(fleet.db).plan_group(group.id, now=NOW)

        decision = plan.decisions[0]
        assert decision.action is SyncAction.SKIP
        assert decision.source_latest == name(20)
        assert decision.target_latest == name(20)
        assert decision.hours_behind == 0.0
        assert decision.reason is not None

    def test_a_target_with_no_snapshots_gets_a_full_send(self, fleet):
        hub = fleet.system("hub1")
        spoke = fleet.system("spoke1")
        group = fleet.group(hub, [hub, spoke], name="empty-target")
        fleet.snaps(hub, "hubpool1", range(1, 21))

        plan = SyncPlanner(fleet.db).plan_group(group.id, now=NOW)

        decision = plan.decisions[0]
        assert decision.action is SyncAction.SYNC
        assert decision.full_send is True
        assert decision.starting_snapshot is None
        assert decision.reason == "no_common_base"

    def test_a_hub_with_no_snapshots_yields_no_pair_for_that_dataset(self, fleet):
        hub = fleet.system("hub1")
        spoke = fleet.system("spoke1")
        group = fleet.group(hub, [hub, spoke], name="empty-hub")
        fleet.snaps(spoke, "spokepool1", [1, 2])

        plan = SyncPlanner(fleet.db).plan_group(group.id, now=NOW)

        assert plan.decisions == []
        assert plan.skipped_reason is None

    def test_a_target_ahead_of_the_hub_is_reported_as_diverged(self, fleet):
        hub = fleet.system("hub1")
        spoke = fleet.system("spoke1")
        group = fleet.group(hub, [hub, spoke], name="diverged")
        fleet.snaps(hub, "hubpool1", range(1, 11))
        fleet.snaps(spoke, "spokepool1", [1, 2])
        # A snapshot the hub has never seen, newer than the incremental base.
        fleet.snapshots.create(
            name=f"spokepool1/{DATASET}@local-only",
            pool="spokepool1",
            dataset=DATASET,
            timestamp=day(9),
            size=1024,
            system_id=spoke.id,
        )

        plan = SyncPlanner(fleet.db).plan_group(group.id, now=NOW)

        decision = plan.decisions[0]
        assert decision.action is SyncAction.SKIP
        assert decision.reason == PlanReason.TARGET_DIVERGED.value

    def test_a_target_without_an_ssh_identity_says_so(self, fleet):
        hub = fleet.system("hub1")
        spoke = fleet.system("spoke1", ssh_hostname=None)
        group = fleet.group(hub, [hub, spoke], name="no-ssh")
        fleet.snaps(hub, "hubpool1", range(1, 21))
        fleet.snaps(spoke, "spokepool1", [1, 2])

        plan = SyncPlanner(fleet.db).plan_group(group.id, now=NOW)

        decision = plan.decisions[0]
        assert decision.action is SyncAction.SKIP
        assert decision.reason == PlanReason.MISSING_SSH_IDENTITY.value

    def test_snapshots_newer_than_the_age_cap_are_not_sent(self, fleet):
        """The documented policy the old code never applied."""
        hub = fleet.system("hub1")
        spoke = fleet.system("spoke1")
        group = fleet.group(hub, [hub, spoke], name="age-cap")
        fleet.snaps(hub, "hubpool1", range(1, 21))
        fleet.snaps(spoke, "spokepool1", [1, 2])

        # 36h after the last hub snapshot: with a 72h minimum age the newest
        # two snapshots are too recent to send.
        plan = SyncPlanner(fleet.db).plan_group(
            group.id, now=day(20) + timedelta(hours=36)
        )

        decision = plan.decisions[0]
        assert decision.ending_snapshot == name(18)


class TestPairEnumeration:
    def test_two_datasets_and_two_targets_give_four_decisions(self, fleet):
        hub = fleet.system("hub1")
        spoke_a = fleet.system("spoke1")
        spoke_b = fleet.system("spoke2")
        group = fleet.group(hub, [hub, spoke_a, spoke_b], name="matrix")

        for dataset in ("DATA1", "DATA2"):
            fleet.snaps(hub, "hubpool1", range(1, 21), dataset=dataset)
            fleet.snaps(spoke_a, "spokepool1", [1, 2], dataset=dataset)
            fleet.snaps(spoke_b, "spokepool2", [1, 2], dataset=dataset)

        plan = SyncPlanner(fleet.db).plan_group(group.id, now=NOW)

        assert len(plan.decisions) == 4
        assert len(plan.instructions) == 4
        pairs = {(d.dataset, d.target.hostname) for d in plan.decisions}
        assert pairs == {
            ("DATA1", "spoke1"),
            ("DATA1", "spoke2"),
            ("DATA2", "spoke1"),
            ("DATA2", "spoke2"),
        }

    def test_the_hub_is_never_its_own_target(self, fleet):
        hub = fleet.system("hub1")
        spoke = fleet.system("spoke1")
        group = fleet.group(hub, [hub, spoke], name="no-self")
        fleet.snaps(hub, "hubpool1", range(1, 21))
        fleet.snaps(spoke, "spokepool1", [1, 2])

        plan = SyncPlanner(fleet.db).plan_group(group.id, now=NOW)

        assert all(d.target.id != hub.id for d in plan.decisions)

    def test_the_current_pool_is_used_when_a_dataset_moved_pools(self, fleet):
        """Pool is taken from the newest snapshot, not an arbitrary row."""
        hub = fleet.system("hub1")
        spoke = fleet.system("spoke1")
        group = fleet.group(hub, [hub, spoke], name="moved")
        fleet.snaps(hub, "oldpool", [1, 2])
        fleet.snaps(hub, "newpool", range(3, 21))
        fleet.snaps(spoke, "spokepool1", [1, 2])

        plan = SyncPlanner(fleet.db).plan_group(group.id, now=NOW)

        assert plan.decisions[0].source_pool == "newpool"

    def test_duplicate_snapshot_rows_do_not_change_the_window(self, fleet):
        """Ingestion has no unique constraint yet, so duplicates exist."""
        hub = fleet.system("hub1")
        spoke = fleet.system("spoke1")
        group = fleet.group(hub, [hub, spoke], name="dupes")
        fleet.snaps(hub, "hubpool1", range(1, 21))
        fleet.snaps(hub, "hubpool1", range(1, 21))  # reported twice
        fleet.snaps(spoke, "spokepool1", [1, 2])

        plan = SyncPlanner(fleet.db).plan_group(group.id, now=NOW)

        assert len(plan.decisions) == 1
        assert plan.decisions[0].ending_snapshot == name(20)
        assert plan.decisions[0].starting_snapshot == name(2)


class TestPlanForSystem:
    def test_the_hub_receives_every_pair_it_must_execute(self, fleet):
        hub = fleet.system("hub1")
        spoke_a = fleet.system("spoke1")
        spoke_b = fleet.system("spoke2")
        fleet.group(hub, [hub, spoke_a, spoke_b], name="exec")
        fleet.snaps(hub, "hubpool1", range(1, 21))
        fleet.snaps(spoke_a, "spokepool1", [1, 2])
        fleet.snaps(spoke_b, "spokepool2", [1, 2])

        decisions = SyncPlanner(fleet.db).plan_for_system(hub.id, now=NOW)

        assert len(decisions) == 2
        assert {d.target.hostname for d in decisions} == {"spoke1", "spoke2"}

    def test_a_spoke_is_asked_to_execute_nothing(self, fleet):
        """Commands send from the source's pool, so only the hub can run them."""
        hub = fleet.system("hub1")
        spoke = fleet.system("spoke1")
        fleet.group(hub, [hub, spoke], name="spoke-view")
        fleet.snaps(hub, "hubpool1", range(1, 21))
        fleet.snaps(spoke, "spokepool1", [1, 2])

        decisions = SyncPlanner(fleet.db).plan_for_system(spoke.id, now=NOW)

        assert decisions == []

    def test_an_unknown_group_filter_raises(self, fleet):
        import uuid

        hub = fleet.system("hub1")

        with pytest.raises(SyncGroupNotFound):
            SyncPlanner(fleet.db).plan_for_system(hub.id, sync_group_id=uuid.uuid4())

    def test_disabled_groups_are_excluded_when_no_filter_is_given(self, fleet):
        hub = fleet.system("hub1")
        spoke = fleet.system("spoke1")
        fleet.group(hub, [hub, spoke], name="off", enabled=False)
        fleet.snaps(hub, "hubpool1", range(1, 21))
        fleet.snaps(spoke, "spokepool1", [1, 2])

        decisions = SyncPlanner(fleet.db).plan_for_system(hub.id, now=NOW)

        assert decisions == []


class TestQueryEfficiency:
    def test_planning_does_not_scale_with_dataset_count(self, fleet):
        """Snapshots are loaded once per group, not per dataset per system.

        The old service loaded every snapshot row for every system just to
        collect dataset names, then re-issued get_by_dataset four or more times
        for each (dataset, target) pair.
        """
        from sqlalchemy import event

        hub = fleet.system("hub1")
        spoke = fleet.system("spoke1")
        group = fleet.group(hub, [hub, spoke], name="wide")
        for index in range(12):
            dataset = f"DATA{index}"
            fleet.snaps(hub, "hubpool1", range(1, 6), dataset=dataset)
            fleet.snaps(spoke, "spokepool1", [1], dataset=dataset)

        statements = []
        engine = fleet.db.get_bind()

        def record(conn, cursor, statement, params, context, executemany):
            if statement.strip().upper().startswith("SELECT"):
                statements.append(statement)

        event.listen(engine, "before_cursor_execute", record)
        try:
            plan = SyncPlanner(fleet.db).plan_group(group.id, now=NOW)
        finally:
            event.remove(engine, "before_cursor_execute", record)

        assert len(plan.decisions) == 12
        # Group, associations, two systems, one snapshot sweep -- a small
        # constant. Twelve datasets must not mean dozens of queries.
        assert len(statements) < 12, (
            f"planning 12 datasets issued {len(statements)} SELECTs: {statements}"
        )
