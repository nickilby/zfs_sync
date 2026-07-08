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
