"""Integration tests for sync instructions endpoints."""

from datetime import datetime, timezone

from fastapi import status

from zfs_sync.database.repositories import SnapshotRepository, SyncGroupRepository, SystemRepository


class TestSyncInstructionsEndpoints:
    """Test suite for sync instructions API."""

    def test_l1s4dat1_sync_instructions_72h_gate(self, test_client, test_db):
        """
        End-to-end test for /sync/instructions/{system_id} using the L1S4DAT1 scenario.

        Verifies that the API returns dataset instructions matching the 72-hour gate:
        - starting_snapshot == 2025-10-30-000000 (last common snapshot)
        - ending_snapshot == 2025-12-01-000000 (latest snapshot older than now-72h)
        - commands include an incremental zfs send -c -I ... from starting to ending.
        """
        system_repo = SystemRepository(test_db)
        snapshot_repo = SnapshotRepository(test_db)
        sync_group_repo = SyncGroupRepository(test_db)

        # Create systems (source and target)
        source = system_repo.create(
            hostname="hqs10-api",
            platform="linux",
            connectivity_status="online",
            ssh_hostname="hqs10.example.com",
            ssh_user="root",
            ssh_port=22,
        )
        target = system_repo.create(
            hostname="hqs7-api",
            platform="linux",
            connectivity_status="online",
            ssh_hostname="hqs7-san",
            ssh_user="root",
            ssh_port=22,
        )

        # Create sync group and add both systems
        sync_group = sync_group_repo.create(
            name="l1s4dat1-api-72h-test",
            description="API test for L1S4DAT1 72h gate",
            enabled=True,
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
                name=f"hqs10p1/L1S4DAT1@{name}",
                pool="hqs10p1",
                dataset="L1S4DAT1",
                system_id=source.id,
                timestamp=ts,
                size=0,
            )

        for name, ts in target_snapshots:
            snapshot_repo.create(
                name=f"hqs7p1/L1S4DAT1@{name}",
                pool="hqs7p1",
                dataset="L1S4DAT1",
                system_id=target.id,
                timestamp=ts,
                size=0,
            )

        # Call the sync instructions endpoint for the target system
        response = test_client.get(
            f"/api/v1/sync/instructions/{target.id}",
            params={"sync_group_id": str(sync_group.id), "include_diagnostics": "true"},
        )
        assert response.status_code == status.HTTP_200_OK
        payload = response.json()

        assert payload["dataset_count"] > 0
        l1s4 = None
        for ds in payload["datasets"]:
            if ds["dataset"] == "L1S4DAT1":
                l1s4 = ds
                break

        assert l1s4 is not None, f"No L1S4DAT1 dataset in instructions: {payload['datasets']}"

        assert (
            l1s4["starting_snapshot"] == "2025-10-30-000000"
        ), f"Expected starting_snapshot=2025-10-30-000000, got {l1s4['starting_snapshot']}"
        # Ending snapshot is gated by 72h rule: latest midnight snapshot older than now-72h
        # As time progresses, this will shift (e.g., on Dec 5 it's 2025-12-02, on Dec 6 it's 2025-12-03)
        assert l1s4["ending_snapshot"] in [
            "2025-12-01-000000",
            "2025-12-02-000000",
            "2025-12-03-000000",
        ], f"Expected ending_snapshot to be a recent midnight snapshot gated by 72h, got {l1s4['ending_snapshot']}"

        commands = l1s4.get("commands", [])
        assert commands, f"Expected at least one command for L1S4DAT1, got {commands}"
        cmd = commands[0]

        assert "zfs send" in cmd and "-I" in cmd, f"Unexpected command: {cmd}"
        assert "@2025-10-30-000000" in cmd, f"Incremental base missing in command: {cmd}"
        # The ending snapshot in the command should match the instruction's ending_snapshot
        assert (
            f"@{l1s4['ending_snapshot']}" in cmd
        ), f"Ending snapshot {l1s4['ending_snapshot']} missing in command: {cmd}"
