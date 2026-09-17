"""Unit tests for SyncSchedulerService."""

import asyncio

import pytest

from zfs_sync.database.repositories import SyncGroupRepository, SystemRepository
from zfs_sync.services.sync_scheduler import SyncSchedulerService


@pytest.fixture
def anyio_backend():
    """Force async tests in this module to run on asyncio only."""
    return "asyncio"


@pytest.mark.anyio
async def test_start_scheduler_noop_when_disabled():
    """Scheduler should not start when auto-sync is disabled."""
    scheduler = SyncSchedulerService()
    scheduler.settings.auto_sync_enabled = False

    await scheduler.start_scheduler()

    assert getattr(scheduler, "_running") is False
    assert getattr(scheduler, "_task") is None


@pytest.mark.anyio
async def test_start_and_stop_scheduler_lifecycle(monkeypatch):
    """Scheduler should create and then cleanly stop its background task."""
    scheduler = SyncSchedulerService()
    scheduler.settings.auto_sync_enabled = True

    async def _fake_scheduler_loop():
        while getattr(scheduler, "_running"):
            await asyncio.sleep(0.01)

    monkeypatch.setattr(scheduler, "_scheduler_loop", _fake_scheduler_loop)

    await scheduler.start_scheduler()
    assert getattr(scheduler, "_running") is True
    assert getattr(scheduler, "_task") is not None

    await scheduler.stop_scheduler()

    assert getattr(scheduler, "_running") is False
    task = getattr(scheduler, "_task")
    assert task is not None
    assert task.done()


def test_should_process_sync_group_requires_multiple_systems(test_db, sample_system_data):
    """Groups with fewer than two systems are skipped."""
    system_repo = SystemRepository(test_db)
    system = system_repo.create(**sample_system_data)

    sync_group_repo = SyncGroupRepository(test_db)
    sync_group = sync_group_repo.create(name="single-system", description="single", enabled=True)
    sync_group_repo.add_system(sync_group.id, system.id)

    scheduler = SyncSchedulerService()

    assert scheduler.should_process_sync_group(sync_group.id, test_db) is False


def test_should_process_sync_group_accepts_enabled_group_with_two_systems(
    test_db, sample_system_data
):
    """Enabled groups with at least two systems should be eligible for processing."""
    system_repo = SystemRepository(test_db)
    system1 = system_repo.create(**sample_system_data)
    system2_data = sample_system_data.copy()
    system2_data["hostname"] = "test-system-2"
    system2 = system_repo.create(**system2_data)

    sync_group_repo = SyncGroupRepository(test_db)
    sync_group = sync_group_repo.create(name="pair", description="pair", enabled=True)
    sync_group_repo.add_system(sync_group.id, system1.id)
    sync_group_repo.add_system(sync_group.id, system2.id)

    scheduler = SyncSchedulerService()

    assert scheduler.should_process_sync_group(sync_group.id, test_db) is True


class TestSchedulerRecordsState:
    """The scheduler must do the work its docstring claims.

    It previously called generate_dataset_sync_instructions and discarded the
    result while claiming to update sync states, so nothing in the automatic
    path ever wrote sync_states -- the table the dashboard and status summary
    read. No test caught it because none asserted the side effect.
    """

    @staticmethod
    def _fleet(db):
        from datetime import datetime, timezone

        from zfs_sync.database.repositories import SnapshotRepository

        systems = SystemRepository(db)
        groups = SyncGroupRepository(db)
        snapshots = SnapshotRepository(db)

        hub = systems.create(
            hostname="hub1", platform="linux", connectivity_status="online",
            ssh_hostname="hub1-san",
        )
        spoke = systems.create(
            hostname="spoke1", platform="linux", connectivity_status="online",
            ssh_hostname="spoke1-san",
        )
        for number in range(1, 21):
            snapshots.create(
                name=f"hubpool1/DATA1@2025-01-{number:02d}-000000",
                pool="hubpool1", dataset="DATA1", system_id=hub.id,
                timestamp=datetime(2025, 1, number, tzinfo=timezone.utc), size=1024,
            )
        for number in (1, 2):
            snapshots.create(
                name=f"spokepool1/DATA1@2025-01-{number:02d}-000000",
                pool="spokepool1", dataset="DATA1", system_id=spoke.id,
                timestamp=datetime(2025, 1, number, tzinfo=timezone.utc), size=1024,
            )

        group = groups.create(name="sched", directional=True, hub_system_id=hub.id)
        groups.add_system(group.id, hub.id)
        groups.add_system(group.id, spoke.id)
        return group, hub, spoke

    def test_a_pass_writes_sync_states(self, test_db):
        from zfs_sync.database.repositories import SyncStateRepository

        group, _hub, spoke = self._fleet(test_db)
        scheduler = SyncSchedulerService()

        scheduler._process_sync_group(group.id, test_db)

        state = SyncStateRepository(test_db).get_by_dataset(
            sync_group_id=group.id, dataset="DATA1", system_id=spoke.id
        )
        assert state is not None, "the scheduler must record what it planned"
        assert state.status == "out_of_sync"

    def test_the_status_summary_is_populated_afterwards(self, test_db):
        from zfs_sync.services.sync.state import SyncStateService

        group, _hub, _spoke = self._fleet(test_db)
        scheduler = SyncSchedulerService()

        assert SyncStateService(test_db).get_status_summary(group.id)["total_states"] == 0

        scheduler._process_sync_group(group.id, test_db)

        summary = SyncStateService(test_db).get_status_summary(group.id)
        assert summary["total_states"] == 1
        assert summary["out_of_sync_count"] == 1

    def test_a_disabled_group_records_nothing(self, test_db):
        from zfs_sync.database.repositories import SyncStateRepository

        group, _hub, _spoke = self._fleet(test_db)
        SyncGroupRepository(test_db).update(group.id, enabled=False)
        scheduler = SyncSchedulerService()

        scheduler._process_sync_group(group.id, test_db)

        assert SyncStateRepository(test_db).get_by_sync_group(group.id) == []


@pytest.mark.anyio
async def test_a_pass_does_not_block_the_event_loop(test_db, monkeypatch):
    """Scheduler work runs in a worker thread.

    It used to call synchronous SQLAlchemy directly inside its asyncio task,
    stalling the single-worker API -- including the health check -- for the
    duration of a scan.
    """
    import threading

    scheduler = SyncSchedulerService()
    worker_threads = []

    def record_thread() -> None:
        worker_threads.append(threading.current_thread().name)

    monkeypatch.setattr(scheduler, "_process_all_sync_groups_blocking", record_thread)

    main_thread = threading.current_thread().name
    await scheduler._process_all_sync_groups()

    assert worker_threads, "the blocking body should have run"
    assert worker_threads[0] != main_thread, (
        f"scheduler work ran on the event loop thread ({main_thread})"
    )
