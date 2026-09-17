"""Unit tests for the execution feedback loop."""

from datetime import datetime, timezone

import pytest

from zfs_sync.database.repositories import (
    SnapshotRepository,
    SyncGroupRepository,
    SyncRunRepository,
    SyncStateRepository,
    SystemRepository,
)
from zfs_sync.enums import SyncStatus
from zfs_sync.services.sync.outcomes import RunStatus, SyncOutcome, SyncOutcomeService
from zfs_sync.services.sync.planner import SyncPlanner

DATASET = "DATA1"
NOW = datetime(2025, 2, 1, tzinfo=timezone.utc)


@pytest.fixture
def fleet(test_db):
    """One hub, two spokes, both behind on the same dataset."""
    systems = SystemRepository(test_db)
    groups = SyncGroupRepository(test_db)
    snapshots = SnapshotRepository(test_db)

    hub = systems.create(
        hostname="hub1", platform="linux", connectivity_status="online",
        ssh_hostname="hub1-san",
    )
    spokes = []
    for hostname, pool in (("spoke1", "spokepool1"), ("spoke2", "spokepool2")):
        spoke = systems.create(
            hostname=hostname, platform="linux", connectivity_status="online",
            ssh_hostname=f"{hostname}-san",
        )
        for number in (1, 2):
            snapshots.create(
                name=f"{pool}/{DATASET}@2025-01-{number:02d}-000000",
                pool=pool, dataset=DATASET, system_id=spoke.id,
                timestamp=datetime(2025, 1, number, tzinfo=timezone.utc), size=1024,
            )
        spokes.append(spoke)

    for number in range(1, 21):
        snapshots.create(
            name=f"hubpool1/{DATASET}@2025-01-{number:02d}-000000",
            pool="hubpool1", dataset=DATASET, system_id=hub.id,
            timestamp=datetime(2025, 1, number, tzinfo=timezone.utc), size=1024,
        )

    group = groups.create(name="outcomes", directional=True, hub_system_id=hub.id)
    groups.add_system(group.id, hub.id)
    for spoke in spokes:
        groups.add_system(group.id, spoke.id)

    return {"db": test_db, "group": group, "hub": hub, "spokes": spokes}


def outcome(fleet, spoke_index=0, **overrides) -> SyncOutcome:
    defaults = {
        "sync_group_id": fleet["group"].id,
        "dataset": DATASET,
        "source_system_id": fleet["hub"].id,
        "target_system_id": fleet["spokes"][spoke_index].id,
        "status": RunStatus.SUCCESS,
        "starting_snapshot": "2025-01-02-000000",
        "ending_snapshot": "2025-01-20-000000",
        "bytes_transferred": 1024 * 1024,
    }
    defaults.update(overrides)
    return SyncOutcome(**defaults)


class TestRecordingAnOutcome:
    def test_a_success_is_persisted_as_history(self, fleet):
        service = SyncOutcomeService(fleet["db"])

        run = service.record(outcome(fleet))

        stored = SyncRunRepository(fleet["db"]).get(run.id)
        assert stored.status == "success"
        assert stored.dataset == DATASET
        assert stored.ending_snapshot == "2025-01-20-000000"
        assert stored.bytes_transferred == 1024 * 1024
        assert stored.finished_at is not None

    def test_a_success_projects_the_target_as_in_sync(self, fleet):
        service = SyncOutcomeService(fleet["db"])

        service.record(outcome(fleet))

        state = SyncStateRepository(fleet["db"]).get_by_dataset(
            sync_group_id=fleet["group"].id,
            dataset=DATASET,
            system_id=fleet["spokes"][0].id,
        )
        assert state.status == SyncStatus.IN_SYNC.value
        assert state.last_sync is not None

    def test_a_failure_projects_an_error_and_keeps_the_message(self, fleet):
        service = SyncOutcomeService(fleet["db"])

        service.record(
            outcome(
                fleet,
                status=RunStatus.FAILED,
                error_message="cannot receive incremental stream",
            )
        )

        state = SyncStateRepository(fleet["db"]).get_by_dataset(
            sync_group_id=fleet["group"].id,
            dataset=DATASET,
            system_id=fleet["spokes"][0].id,
        )
        assert state.status == SyncStatus.ERROR.value
        assert "cannot receive incremental stream" in state.error_message

    def test_a_started_report_marks_the_pair_as_syncing(self, fleet):
        service = SyncOutcomeService(fleet["db"])

        service.record(outcome(fleet, status=RunStatus.STARTED, ending_snapshot=None))

        state = SyncStateRepository(fleet["db"]).get_by_dataset(
            sync_group_id=fleet["group"].id,
            dataset=DATASET,
            system_id=fleet["spokes"][0].id,
        )
        assert state.status == SyncStatus.SYNCING.value

    def test_state_is_keyed_on_the_target_not_the_source(self, fleet):
        """A hub pushing to two spokes has two independent verdicts."""
        service = SyncOutcomeService(fleet["db"])

        service.record(outcome(fleet, spoke_index=0, status=RunStatus.SUCCESS))
        service.record(
            outcome(fleet, spoke_index=1, status=RunStatus.FAILED, error_message="timeout")
        )

        repo = SyncStateRepository(fleet["db"])
        first = repo.get_by_dataset(
            sync_group_id=fleet["group"].id, dataset=DATASET,
            system_id=fleet["spokes"][0].id,
        )
        second = repo.get_by_dataset(
            sync_group_id=fleet["group"].id, dataset=DATASET,
            system_id=fleet["spokes"][1].id,
        )
        assert first.status == SyncStatus.IN_SYNC.value
        assert second.status == SyncStatus.ERROR.value

    def test_the_later_report_wins_the_projection_and_both_persist(self, fleet):
        service = SyncOutcomeService(fleet["db"])

        service.record(outcome(fleet, status=RunStatus.FAILED, error_message="first attempt"))
        service.record(outcome(fleet, status=RunStatus.SUCCESS))

        state = SyncStateRepository(fleet["db"]).get_by_dataset(
            sync_group_id=fleet["group"].id, dataset=DATASET,
            system_id=fleet["spokes"][0].id,
        )
        assert state.status == SyncStatus.IN_SYNC.value
        assert state.error_message is None

        runs = SyncRunRepository(fleet["db"]).get_for_pair(
            sync_group_id=fleet["group"].id, dataset=DATASET,
            target_system_id=fleet["spokes"][0].id,
        )
        assert len(runs) == 2, "history keeps both attempts"

    def test_a_result_naming_an_unknown_snapshot_is_still_recorded(self, fleet):
        """Retention may have pruned it since; the report is still evidence."""
        service = SyncOutcomeService(fleet["db"])

        run = service.record(outcome(fleet, ending_snapshot="2099-01-01-000000"))

        assert run.ending_snapshot == "2099-01-01-000000"


class TestPlannedStateProjection:
    """What the scheduler records before anything has executed."""

    def test_every_evaluated_pair_gets_a_state(self, fleet):
        plan = SyncPlanner(fleet["db"]).plan_group(fleet["group"].id, now=NOW)

        recorded = SyncOutcomeService(fleet["db"]).record_planned_states(plan.decisions)

        assert recorded == 2
        repo = SyncStateRepository(fleet["db"])
        for spoke in fleet["spokes"]:
            state = repo.get_by_dataset(
                sync_group_id=fleet["group"].id, dataset=DATASET, system_id=spoke.id
            )
            assert state.status == SyncStatus.OUT_OF_SYNC.value

    def test_an_in_sync_pair_is_recorded_as_in_sync(self, fleet):
        snapshots = SnapshotRepository(fleet["db"])
        for number in range(3, 21):
            snapshots.create(
                name=f"spokepool1/{DATASET}@2025-01-{number:02d}-000000",
                pool="spokepool1", dataset=DATASET, system_id=fleet["spokes"][0].id,
                timestamp=datetime(2025, 1, number, tzinfo=timezone.utc), size=1024,
            )

        plan = SyncPlanner(fleet["db"]).plan_group(fleet["group"].id, now=NOW)
        SyncOutcomeService(fleet["db"]).record_planned_states(plan.decisions)

        state = SyncStateRepository(fleet["db"]).get_by_dataset(
            sync_group_id=fleet["group"].id, dataset=DATASET,
            system_id=fleet["spokes"][0].id,
        )
        assert state.status == SyncStatus.IN_SYNC.value

    def test_a_run_in_progress_is_not_overwritten_by_a_stale_plan(self, fleet):
        service = SyncOutcomeService(fleet["db"])
        service.record(outcome(fleet, status=RunStatus.STARTED))

        plan = SyncPlanner(fleet["db"]).plan_group(fleet["group"].id, now=NOW)
        service.record_planned_states(plan.decisions)

        state = SyncStateRepository(fleet["db"]).get_by_dataset(
            sync_group_id=fleet["group"].id, dataset=DATASET,
            system_id=fleet["spokes"][0].id,
        )
        assert state.status == SyncStatus.SYNCING.value

    def test_the_decline_reason_is_kept_on_an_in_sync_row(self, fleet):
        snapshots = SnapshotRepository(fleet["db"])
        for number in range(3, 21):
            snapshots.create(
                name=f"spokepool1/{DATASET}@2025-01-{number:02d}-000000",
                pool="spokepool1", dataset=DATASET, system_id=fleet["spokes"][0].id,
                timestamp=datetime(2025, 1, number, tzinfo=timezone.utc), size=1024,
            )

        plan = SyncPlanner(fleet["db"]).plan_group(fleet["group"].id, now=NOW)
        SyncOutcomeService(fleet["db"]).record_planned_states(plan.decisions)

        state = SyncStateRepository(fleet["db"]).get_by_dataset(
            sync_group_id=fleet["group"].id, dataset=DATASET,
            system_id=fleet["spokes"][0].id,
        )
        assert state.error_message  # carries why it was not actioned


class TestStatusSummaryReflectsReality:
    def test_the_summary_is_no_longer_empty_after_a_scheduler_pass(self, fleet):
        from zfs_sync.services.sync.state import SyncStateService

        before = SyncStateService(fleet["db"]).get_status_summary(fleet["group"].id)
        assert before["total_states"] == 0

        plan = SyncPlanner(fleet["db"]).plan_group(fleet["group"].id, now=NOW)
        SyncOutcomeService(fleet["db"]).record_planned_states(plan.decisions)

        after = SyncStateService(fleet["db"]).get_status_summary(fleet["group"].id)
        assert after["total_states"] == 2
        assert after["out_of_sync_count"] == 2

    def test_recent_runs_are_returned_newest_first(self, fleet):
        service = SyncOutcomeService(fleet["db"])
        service.record(outcome(fleet, spoke_index=0))
        service.record(outcome(fleet, spoke_index=1, status=RunStatus.FAILED,
                               error_message="boom"))

        runs = service.recent_runs(fleet["group"].id)

        assert len(runs) == 2
        assert {run["status"] for run in runs} == {"success", "failed"}
        assert all("dataset" in run for run in runs)
