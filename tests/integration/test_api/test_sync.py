"""Integration tests for sync instructions endpoints."""

from datetime import datetime, timezone

from fastapi import status

from zfs_sync.database.repositories import SnapshotRepository, SyncGroupRepository, SystemRepository


class TestSyncInstructionsEndpoints:
    """Test suite for sync instructions API."""

    def test_data1_sync_instructions_72h_gate(self, test_client, test_db):
        """
        End-to-end test for /sync/instructions/{system_id} using the DATA1 scenario.

        Verifies the API returns dataset instructions matching the 72-hour gate:
        - starting_snapshot == 2025-10-30-000000 (last common snapshot)
        - ending_snapshot is the latest midnight snapshot older than now-72h
        - commands include an incremental zfs send -c -I ... from start to end

        Instructions are requested as the *source*. Commands send from the
        source's pool, so only the source can run them; asking as the target
        previously returned a command that would fail on the machine it was
        handed to.
        """
        system_repo = SystemRepository(test_db)
        snapshot_repo = SnapshotRepository(test_db)
        sync_group_repo = SyncGroupRepository(test_db)

        # Create systems (source and target)
        source = system_repo.create(
            hostname="hub1-api",
            platform="linux",
            connectivity_status="online",
            ssh_hostname="hub1.example.com",
            ssh_user="root",
            ssh_port=22,
        )
        target = system_repo.create(
            hostname="spoke1-api",
            platform="linux",
            connectivity_status="online",
            ssh_hostname="spoke1-san",
            ssh_user="root",
            ssh_port=22,
        )

        # Create sync group (directional with source as hub) and add both systems
        sync_group = sync_group_repo.create(
            name="data1-api-72h-test",
            description="API test for DATA1 72h gate",
            enabled=True,
            directional=True,
            hub_system_id=source.id,
        )
        sync_group_repo.add_system(sync_group.id, source.id)
        sync_group_repo.add_system(sync_group.id, target.id)

        # Source snapshots (same shape as unit test scenario)
        source_snapshots = [
            # Common snapshots
            ("2025-10-09-000000", datetime(2025, 10, 9, 0, 0, 0, tzinfo=timezone.utc)),
            ("2025-10-16-000000", datetime(2025, 10, 16, 0, 0, 0, tzinfo=timezone.utc)),
            ("2025-10-23-000000", datetime(2025, 10, 23, 0, 0, 0, tzinfo=timezone.utc)),
            ("2025-10-30-000000", datetime(2025, 10, 30, 0, 0, 0, tzinfo=timezone.utc)),
            # Older unique snapshots
            ("2025-09-04-000000", datetime(2025, 9, 4, 0, 0, 0, tzinfo=timezone.utc)),
            ("2025-09-11-000000", datetime(2025, 9, 11, 0, 0, 0, tzinfo=timezone.utc)),
            ("2025-09-18-000000", datetime(2025, 9, 18, 0, 0, 0, tzinfo=timezone.utc)),
            ("2025-09-25-000000", datetime(2025, 9, 25, 0, 0, 0, tzinfo=timezone.utc)),
            ("2025-10-02-000000", datetime(2025, 10, 2, 0, 0, 0, tzinfo=timezone.utc)),
            # Newer unique snapshots on source
            ("2025-11-06-000000", datetime(2025, 11, 6, 0, 0, 0, tzinfo=timezone.utc)),
            ("2025-11-13-000000", datetime(2025, 11, 13, 0, 0, 0, tzinfo=timezone.utc)),
            ("2025-11-18-000000", datetime(2025, 11, 18, 0, 0, 0, tzinfo=timezone.utc)),
            ("2025-11-19-000000", datetime(2025, 11, 19, 0, 0, 0, tzinfo=timezone.utc)),
            ("2025-11-20-000000", datetime(2025, 11, 20, 0, 0, 0, tzinfo=timezone.utc)),
            ("2025-11-21-000000", datetime(2025, 11, 21, 0, 0, 0, tzinfo=timezone.utc)),
            ("2025-11-22-000000", datetime(2025, 11, 22, 0, 0, 0, tzinfo=timezone.utc)),
            ("2025-11-23-000000", datetime(2025, 11, 23, 0, 0, 0, tzinfo=timezone.utc)),
            ("2025-11-24-000000", datetime(2025, 11, 24, 0, 0, 0, tzinfo=timezone.utc)),
            ("2025-11-25-000000", datetime(2025, 11, 25, 0, 0, 0, tzinfo=timezone.utc)),
            ("2025-11-26-000000", datetime(2025, 11, 26, 0, 0, 0, tzinfo=timezone.utc)),
            ("2025-11-27-000000", datetime(2025, 11, 27, 0, 0, 0, tzinfo=timezone.utc)),
            ("2025-11-28-000000", datetime(2025, 11, 28, 0, 0, 0, tzinfo=timezone.utc)),
            ("2025-11-29-000000", datetime(2025, 11, 29, 0, 0, 0, tzinfo=timezone.utc)),
            ("2025-11-30-000000", datetime(2025, 11, 30, 0, 0, 0, tzinfo=timezone.utc)),
            ("2025-12-01-000000", datetime(2025, 12, 1, 0, 0, 0, tzinfo=timezone.utc)),
            ("2025-12-01-120000", datetime(2025, 12, 1, 12, 0, 0, tzinfo=timezone.utc)),
            ("2025-12-02-000000", datetime(2025, 12, 2, 0, 0, 0, tzinfo=timezone.utc)),
            ("2025-12-02-120000", datetime(2025, 12, 2, 12, 0, 0, tzinfo=timezone.utc)),
            ("2025-12-03-000000", datetime(2025, 12, 3, 0, 0, 0, tzinfo=timezone.utc)),
            ("2025-12-03-120000", datetime(2025, 12, 3, 12, 0, 0, tzinfo=timezone.utc)),
        ]

        target_snapshots = [
            ("2025-10-08-000000", datetime(2025, 10, 8, 0, 0, 0, tzinfo=timezone.utc)),
            ("2025-10-10-000000", datetime(2025, 10, 10, 0, 0, 0, tzinfo=timezone.utc)),
            ("2025-10-11-000000", datetime(2025, 10, 11, 0, 0, 0, tzinfo=timezone.utc)),
            ("2025-10-12-000000", datetime(2025, 10, 12, 0, 0, 0, tzinfo=timezone.utc)),
            ("2025-10-13-000000", datetime(2025, 10, 13, 0, 0, 0, tzinfo=timezone.utc)),
            ("2025-10-14-000000", datetime(2025, 10, 14, 0, 0, 0, tzinfo=timezone.utc)),
            ("2025-10-15-000000", datetime(2025, 10, 15, 0, 0, 0, tzinfo=timezone.utc)),
            ("2025-10-16-000000", datetime(2025, 10, 16, 0, 0, 0, tzinfo=timezone.utc)),
            ("2025-10-17-000000", datetime(2025, 10, 17, 0, 0, 0, tzinfo=timezone.utc)),
            ("2025-10-18-000000", datetime(2025, 10, 18, 0, 0, 0, tzinfo=timezone.utc)),
            ("2025-10-19-000000", datetime(2025, 10, 19, 0, 0, 0, tzinfo=timezone.utc)),
            ("2025-10-20-000000", datetime(2025, 10, 20, 0, 0, 0, tzinfo=timezone.utc)),
            ("2025-10-21-000000", datetime(2025, 10, 21, 0, 0, 0, tzinfo=timezone.utc)),
            ("2025-10-22-000000", datetime(2025, 10, 22, 0, 0, 0, tzinfo=timezone.utc)),
            ("2025-10-23-000000", datetime(2025, 10, 23, 0, 0, 0, tzinfo=timezone.utc)),
            ("2025-10-24-000000", datetime(2025, 10, 24, 0, 0, 0, tzinfo=timezone.utc)),
            ("2025-10-25-000000", datetime(2025, 10, 25, 0, 0, 0, tzinfo=timezone.utc)),
            ("2025-10-26-000000", datetime(2025, 10, 26, 0, 0, 0, tzinfo=timezone.utc)),
            ("2025-10-27-000000", datetime(2025, 10, 27, 0, 0, 0, tzinfo=timezone.utc)),
            ("2025-10-28-000000", datetime(2025, 10, 28, 0, 0, 0, tzinfo=timezone.utc)),
            ("2025-10-29-000000", datetime(2025, 10, 29, 0, 0, 0, tzinfo=timezone.utc)),
            ("2025-10-30-000000", datetime(2025, 10, 30, 0, 0, 0, tzinfo=timezone.utc)),
            ("2025-10-31-000000", datetime(2025, 10, 31, 0, 0, 0, tzinfo=timezone.utc)),
            ("2025-11-01-000000", datetime(2025, 11, 1, 0, 0, 0, tzinfo=timezone.utc)),
            ("2025-11-02-000000", datetime(2025, 11, 2, 0, 0, 0, tzinfo=timezone.utc)),
            ("2025-11-03-000000", datetime(2025, 11, 3, 0, 0, 0, tzinfo=timezone.utc)),
            ("2025-11-03-120000", datetime(2025, 11, 3, 12, 0, 0, tzinfo=timezone.utc)),
            ("2025-11-04-000000", datetime(2025, 11, 4, 0, 0, 0, tzinfo=timezone.utc)),
        ]

        for name, ts in source_snapshots:
            snapshot_repo.create(
                name=f"hubpool1/DATA1@{name}",
                pool="hubpool1",
                dataset="DATA1",
                system_id=source.id,
                timestamp=ts,
                size=0,
            )

        for name, ts in target_snapshots:
            snapshot_repo.create(
                name=f"spokepool1/DATA1@{name}",
                pool="spokepool1",
                dataset="DATA1",
                system_id=target.id,
                timestamp=ts,
                size=0,
            )

        # Call the sync instructions endpoint as the source, which executes.
        response = test_client.get(
            f"/api/v1/sync/instructions/{source.id}",
            params={"sync_group_id": str(sync_group.id)},
        )
        assert response.status_code == status.HTTP_200_OK
        payload = response.json()

        assert payload["dataset_count"] > 0
        data1 = None
        for ds in payload["datasets"]:
            if ds["dataset"] == "DATA1":
                data1 = ds
                break

        assert data1 is not None, f"No DATA1 dataset in instructions: {payload['datasets']}"

        assert (
            data1["starting_snapshot"] == "2025-10-30-000000"
        ), f"Expected starting_snapshot=2025-10-30-000000, got {data1['starting_snapshot']}"
        # Ending snapshot is gated by 72h rule: latest midnight snapshot older than now-72h
        # As time progresses, this will shift (e.g., on Dec 5 it's 2025-12-02, on Dec 6 it's 2025-12-03)
        assert data1["ending_snapshot"] in [
            "2025-12-01-000000",
            "2025-12-02-000000",
            "2025-12-03-000000",
        ], f"Expected ending_snapshot to be a recent midnight snapshot gated by 72h, got {data1['ending_snapshot']}"

        commands = data1.get("commands", [])
        assert commands, f"Expected at least one command for DATA1, got {commands}"
        cmd = commands[0]

        assert "zfs send" in cmd and "-I" in cmd, f"Unexpected command: {cmd}"
        assert "@2025-10-30-000000" in cmd, f"Incremental base missing in command: {cmd}"
        # The ending snapshot in the command should match the instruction's ending_snapshot
        assert (
            f"@{data1['ending_snapshot']}" in cmd
        ), f"Ending snapshot {data1['ending_snapshot']} missing in command: {cmd}"
        # The command receives into the target's pool over the target's ssh host.
        assert "spokepool1/DATA1" in cmd, f"Target pool missing in command: {cmd}"
        assert "spoke1-san" in cmd, f"Target ssh host missing in command: {cmd}"

    def test_the_target_is_not_asked_to_run_the_source_command(
        self, test_client, test_db
    ):
        """A target receives no instruction, because it cannot execute one."""
        system_repo = SystemRepository(test_db)
        snapshot_repo = SnapshotRepository(test_db)
        sync_group_repo = SyncGroupRepository(test_db)

        source = system_repo.create(
            hostname="hub-exec", platform="linux", connectivity_status="online",
            ssh_hostname="hub-exec-san",
        )
        target = system_repo.create(
            hostname="spoke-exec", platform="linux", connectivity_status="online",
            ssh_hostname="spoke-exec-san",
        )
        sync_group = sync_group_repo.create(
            name="exec-direction", enabled=True, directional=True, hub_system_id=source.id
        )
        sync_group_repo.add_system(sync_group.id, source.id)
        sync_group_repo.add_system(sync_group.id, target.id)

        for number in range(1, 21):
            snapshot_repo.create(
                name=f"hubpool1/DATA1@2025-01-{number:02d}-000000",
                pool="hubpool1", dataset="DATA1", system_id=source.id,
                timestamp=datetime(2025, 1, number, tzinfo=timezone.utc), size=0,
            )
        for number in (1, 2):
            snapshot_repo.create(
                name=f"spokepool1/DATA1@2025-01-{number:02d}-000000",
                pool="spokepool1", dataset="DATA1", system_id=target.id,
                timestamp=datetime(2025, 1, number, tzinfo=timezone.utc), size=0,
            )

        source_view = test_client.get(f"/api/v1/sync/instructions/{source.id}").json()
        target_view = test_client.get(f"/api/v1/sync/instructions/{target.id}").json()

        assert source_view["dataset_count"] == 1
        assert target_view["dataset_count"] == 0

    def test_an_in_sync_fleet_explains_itself(self, test_client, test_db):
        """An empty datasets list comes with a reason per evaluated pair.

        Previously a healthy fleet and a completely suppressed one returned an
        identical empty response.
        """
        system_repo = SystemRepository(test_db)
        snapshot_repo = SnapshotRepository(test_db)
        sync_group_repo = SyncGroupRepository(test_db)

        source = system_repo.create(
            hostname="hub-sync", platform="linux", connectivity_status="online",
            ssh_hostname="hub-sync-san",
        )
        target = system_repo.create(
            hostname="spoke-sync", platform="linux", connectivity_status="online",
            ssh_hostname="spoke-sync-san",
        )
        sync_group = sync_group_repo.create(
            name="already-in-sync", enabled=True, directional=True, hub_system_id=source.id
        )
        sync_group_repo.add_system(sync_group.id, source.id)
        sync_group_repo.add_system(sync_group.id, target.id)

        for system, pool in ((source, "hubpool1"), (target, "spokepool1")):
            for number in range(1, 21):
                snapshot_repo.create(
                    name=f"{pool}/DATA1@2025-01-{number:02d}-000000",
                    pool=pool, dataset="DATA1", system_id=system.id,
                    timestamp=datetime(2025, 1, number, tzinfo=timezone.utc), size=0,
                )

        payload = test_client.get(f"/api/v1/sync/instructions/{source.id}").json()

        assert payload["datasets"] == []
        assert payload["dataset_count"] == 0
        assert len(payload["declined"]) == 1
        declined = payload["declined"][0]
        assert declined["dataset"] == "DATA1"
        assert declined["target_hostname"] == "spoke-sync"
        assert declined["reason"] == "base_equals_end"
        assert declined["hours_behind"] == 0.0
