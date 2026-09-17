"""A znapzend-managed fleet, planned end to end.

znapzend creates and prunes snapshots; this service observes what it produced
and plans replication where znapzend is not already doing it. The join between
them is the snapshot naming convention, which is configuration rather than the
hardcoded midnight rule it used to be.
"""

from datetime import datetime, timezone

import pytest
from fastapi import status

from zfs_sync.database.repositories import (
    SnapshotRepository,
    SyncGroupRepository,
    SystemRepository,
)
from zfs_sync.services.sync.planner import SyncPlanner

DATASET = "DATA1"
ZNAPZEND_PATTERN = r"^\d{4}-\d{2}-\d{2}-\d{6}$"
NOW = datetime(2025, 2, 1, tzinfo=timezone.utc)


def znapzend_names(day: int, hours=(0, 6, 12, 18)):
    """Names as znapzend's default tsformat produces them."""
    return [(f"2025-01-{day:02d}-{hour:02d}0000", datetime(2025, 1, day, hour, tzinfo=timezone.utc))
            for hour in hours]


@pytest.fixture
def znapzend_settings():
    """Settings configured for znapzend naming, restored afterwards."""
    from zfs_sync.config import get_settings

    settings = get_settings()
    original = settings.snapshot_anchor_pattern
    settings.snapshot_anchor_pattern = ZNAPZEND_PATTERN
    yield settings
    settings.snapshot_anchor_pattern = original


@pytest.fixture
def fleet(test_db):
    """A hub and a spoke, both managed by znapzend."""
    systems = SystemRepository(test_db)
    groups = SyncGroupRepository(test_db)
    snapshots = SnapshotRepository(test_db)

    hub = systems.create(
        hostname="hub1", platform="linux", connectivity_status="online",
        ssh_hostname="hub1-san",
    )
    spoke = systems.create(
        hostname="spoke1", platform="linux", connectivity_status="online",
        ssh_hostname="spoke1-san",
    )

    for day in range(1, 11):
        for name, timestamp in znapzend_names(day):
            snapshots.create(
                name=f"hubpool1/{DATASET}@{name}", pool="hubpool1", dataset=DATASET,
                timestamp=timestamp, size=1024, system_id=hub.id,
            )
    # The spoke has only the first day: znapzend has not replicated the rest.
    for name, timestamp in znapzend_names(1):
        snapshots.create(
            name=f"spokepool1/{DATASET}@{name}", pool="spokepool1", dataset=DATASET,
            timestamp=timestamp, size=1024, system_id=spoke.id,
        )

    group = groups.create(name="znapzend", directional=True, hub_system_id=hub.id)
    groups.add_system(group.id, hub.id)
    groups.add_system(group.id, spoke.id)
    return {"db": test_db, "group": group, "hub": hub, "spoke": spoke}


class TestPlanningAZnapzendFleet:
    def test_the_midnight_default_understates_how_current_the_host_is(self, fleet):
        """Without configuring the pattern, only one snapshot a day counts.

        The plan still works, but it targets a snapshot up to 18 hours older
        than the newest one available -- which is why the convention has to be
        configuration.
        """
        plan = SyncPlanner(fleet["db"]).plan_group(fleet["group"].id, now=NOW)

        decision = plan.decisions[0]
        assert decision.ending_snapshot == "2025-01-10-000000"

    def test_configuring_the_pattern_uses_the_newest_snapshot(
        self, fleet, znapzend_settings
    ):
        plan = SyncPlanner(fleet["db"], settings=znapzend_settings).plan_group(
            fleet["group"].id, now=NOW
        )

        decision = plan.decisions[0]
        assert decision.ending_snapshot == "2025-01-10-180000"
        assert decision.starting_snapshot == "2025-01-01-180000"

    def test_the_rendered_command_uses_znapzend_names(self, fleet, znapzend_settings):
        from zfs_sync.services.sync.renderer import render_sync_command

        plan = SyncPlanner(fleet["db"], settings=znapzend_settings).plan_group(
            fleet["group"].id, now=NOW
        )

        command = render_sync_command(plan.instructions[0])

        assert "hubpool1/DATA1@2025-01-01-180000" in command
        assert "hubpool1/DATA1@2025-01-10-180000" in command
        assert "ssh spoke1-san" in command


class TestMixedFleet:
    """Some hosts on znapzend, some on the legacy convention."""

    def test_both_conventions_plan_under_the_znapzend_pattern(
        self, test_db, znapzend_settings
    ):
        systems = SystemRepository(test_db)
        groups = SyncGroupRepository(test_db)
        snapshots = SnapshotRepository(test_db)

        hub = systems.create(
            hostname="hub1", platform="linux", connectivity_status="online",
            ssh_hostname="hub1-san",
        )
        legacy = systems.create(
            hostname="legacy-spoke", platform="linux", connectivity_status="online",
            ssh_hostname="legacy-san",
        )

        # The hub runs znapzend four times a day.
        for day in range(1, 11):
            for name, timestamp in znapzend_names(day):
                snapshots.create(
                    name=f"hubpool1/{DATASET}@{name}", pool="hubpool1", dataset=DATASET,
                    timestamp=timestamp, size=1024, system_id=hub.id,
                )
        # The legacy host only ever took midnight snapshots, which the
        # znapzend pattern also matches.
        for day in (1, 2):
            snapshots.create(
                name=f"legacypool/{DATASET}@2025-01-{day:02d}-000000",
                pool="legacypool", dataset=DATASET,
                timestamp=datetime(2025, 1, day, tzinfo=timezone.utc),
                size=1024, system_id=legacy.id,
            )

        group = groups.create(name="mixed", directional=True, hub_system_id=hub.id)
        groups.add_system(group.id, hub.id)
        groups.add_system(group.id, legacy.id)

        plan = SyncPlanner(test_db, settings=znapzend_settings).plan_group(
            group.id, now=NOW
        )

        decision = plan.decisions[0]
        assert decision.action.value == "sync"
        assert decision.starting_snapshot == "2025-01-02-000000"
        assert decision.ending_snapshot == "2025-01-10-180000"


class TestConfigurationIsValidated:
    def test_an_invalid_pattern_is_rejected_at_startup(self):
        """Better to fail where the pattern is configured than mid-sync."""
        from zfs_sync.config.settings import Settings

        with pytest.raises(ValueError, match="not a valid regex"):
            Settings(snapshot_anchor_pattern="([unclosed")

    def test_a_pattern_matching_nothing_is_reported_per_pair(self, fleet):
        """A misconfigured pattern must be visible, not silently produce
        an empty result."""
        from zfs_sync.config import get_settings

        settings = get_settings()
        original = settings.snapshot_anchor_pattern
        settings.snapshot_anchor_pattern = r"^will-never-match$"
        try:
            plan = SyncPlanner(fleet["db"], settings=settings).plan_group(
                fleet["group"].id, now=NOW
            )
        finally:
            settings.snapshot_anchor_pattern = original

        assert plan.instructions == []
        assert plan.decisions[0].reason == "no_eligible_ending_snapshot"


class TestReportingZnapzendSnapshots:
    def test_znapzend_named_snapshots_ingest_normally(self, test_client):
        """The report hook posts what znapzend created, like any other client."""
        registered = test_client.post(
            "/api/v1/systems",
            json={"hostname": "znapzend-host", "platform": "linux",
                  "ssh_hostname": "znapzend-host-san"},
        ).json()

        rows = [
            {
                "name": f"tank/{DATASET}@{name}",
                "pool": "tank",
                "dataset": DATASET,
                "timestamp": timestamp.isoformat(),
                "size": 1024,
                "system_id": registered["id"],
            }
            for name, timestamp in znapzend_names(1)
        ]

        response = test_client.post(
            "/api/v1/snapshots/batch",
            headers={"X-API-Key": registered["api_key"]},
            params={"reconcile": "true"},
            json=rows,
        )

        assert response.status_code == status.HTTP_201_CREATED
        assert response.json()["created"] == 4

    def test_a_pruned_snapshot_is_removed_on_the_next_report(self, test_client):
        """znapzend expiring a snapshot must be reflected, or the witness would
        keep proposing a base that no longer exists on disk."""
        registered = test_client.post(
            "/api/v1/systems",
            json={"hostname": "pruning-host", "platform": "linux"},
        ).json()

        def report(names):
            return test_client.post(
                "/api/v1/snapshots/batch",
                headers={"X-API-Key": registered["api_key"]},
                params={"reconcile": "true"},
                json=[
                    {
                        "name": f"tank/{DATASET}@{name}", "pool": "tank", "dataset": DATASET,
                        "timestamp": timestamp.isoformat(), "size": 1024,
                        "system_id": registered["id"],
                    }
                    for name, timestamp in names
                ],
            )

        report(znapzend_names(1))
        # znapzend expires the two oldest.
        response = report(znapzend_names(1, hours=(12, 18)))

        assert response.json()["deleted"] == 2
