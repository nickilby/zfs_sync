"""Test to expose the bug where systems with missing snapshots are not detected as out of sync."""

from datetime import datetime, timezone


from zfs_sync.database.repositories import (
    SnapshotRepository,
    SyncGroupRepository,
    SystemRepository,
)
from zfs_sync.services.sync_coordination import SyncCoordinationService
from zfs_sync.services.sync_validators import is_snapshot_out_of_sync_by_24h
from zfs_sync.services.snapshot_comparison import SnapshotComparisonService


class TestSyncMismatchDetection:
    """Test suite to expose sync mismatch detection bugs."""

    def test_hqs7_hqs10_l1s4dat1_mismatch(self, test_db):
        """
        Test that reproduces the HQS7/HQS10 L1S4DAT1 sync issue.

        Scenario:
        - HQS10 (source) has snapshots from 2025-09-04 to 2025-11-30
        - HQS7 (target) has snapshots from 2025-10-08 to 2025-11-04
        - HQS7 is missing many snapshots and should be detected as out of sync
        """
        # Create systems
        system_repo = SystemRepository(test_db)
        hqs10 = system_repo.create(
            hostname="hqs10",
            platform="linux",
            connectivity_status="online",
            ssh_hostname="hqs10.example.com",
            ssh_user="root",
            ssh_port=22,
        )
        hqs7 = system_repo.create(
            hostname="hqs7",
            platform="linux",
            connectivity_status="online",
            ssh_hostname="hqs7.example.com",
            ssh_user="root",
            ssh_port=22,
        )

        # Create sync group
        sync_group_repo = SyncGroupRepository(test_db)
        sync_group = sync_group_repo.create(
            name="test-sync-group",
            description="Test sync group",
            enabled=True,
        )
        sync_group_repo.add_system(sync_group.id, hqs10.id)
        sync_group_repo.add_system(sync_group.id, hqs7.id)

        # Create snapshot repository
        snapshot_repo = SnapshotRepository(test_db)
        comparison_service = SnapshotComparisonService(test_db)

        # HQS10 snapshots (source - has more snapshots, including latest)
        # Weekly snapshots from 2025-09-04 to 2025-11-06, then daily from 2025-11-13 to 2025-11-30
        hqs10_snapshots = [
            # Weekly snapshots
            ("2025-09-04-000000", datetime(2025, 9, 4, 0, 0, 0, tzinfo=timezone.utc)),
            ("2025-09-11-000000", datetime(2025, 9, 11, 0, 0, 0, tzinfo=timezone.utc)),
            ("2025-09-18-000000", datetime(2025, 9, 18, 0, 0, 0, tzinfo=timezone.utc)),
            ("2025-09-25-000000", datetime(2025, 9, 25, 0, 0, 0, tzinfo=timezone.utc)),
            ("2025-10-02-000000", datetime(2025, 10, 2, 0, 0, 0, tzinfo=timezone.utc)),
            ("2025-10-09-000000", datetime(2025, 10, 9, 0, 0, 0, tzinfo=timezone.utc)),
            ("2025-10-16-000000", datetime(2025, 10, 16, 0, 0, 0, tzinfo=timezone.utc)),
            ("2025-10-23-000000", datetime(2025, 10, 23, 0, 0, 0, tzinfo=timezone.utc)),
            ("2025-10-30-000000", datetime(2025, 10, 30, 0, 0, 0, tzinfo=timezone.utc)),
            ("2025-11-06-000000", datetime(2025, 11, 6, 0, 0, 0, tzinfo=timezone.utc)),
            # Daily snapshots
            ("2025-11-13-000000", datetime(2025, 11, 13, 0, 0, 0, tzinfo=timezone.utc)),
            ("2025-11-16-120000", datetime(2025, 11, 16, 12, 0, 0, tzinfo=timezone.utc)),
            ("2025-11-17-000000", datetime(2025, 11, 17, 0, 0, 0, tzinfo=timezone.utc)),
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
            ("2025-11-30-120000", datetime(2025, 11, 30, 12, 0, 0, tzinfo=timezone.utc)),
        ]

        # HQS7 snapshots (target - missing many snapshots, stops at 2025-11-04)
        hqs7_snapshots = [
            # Daily snapshots from 2025-10-08 to 2025-11-04
            ("2025-10-08-000000", datetime(2025, 10, 8, 0, 0, 0, tzinfo=timezone.utc)),
            ("2025-10-09-000000", datetime(2025, 10, 9, 0, 0, 0, tzinfo=timezone.utc)),
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

        # Create snapshots for HQS10
        for snapshot_name, timestamp in hqs10_snapshots:
            snapshot_repo.create(
                name=f"hqs10p1/L1S4DAT1@{snapshot_name}",
                pool="hqs10p1",
                dataset="L1S4DAT1",
                system_id=hqs10.id,
                timestamp=timestamp,
                size=100 * 1024 * 1024 * 1024,  # 100GB
            )

        # Create snapshots for HQS7
        for snapshot_name, timestamp in hqs7_snapshots:
            snapshot_repo.create(
                name=f"hqs7p1/L1S4DAT1@{snapshot_name}",
                pool="hqs7p1",
                dataset="L1S4DAT1",
                system_id=hqs7.id,
                timestamp=timestamp,
                size=50 * 1024 * 1024 * 1024,  # 50GB
            )

        # Test the is_snapshot_out_of_sync_by_24h function directly
        hqs10_snapshot_models = snapshot_repo.get_by_pool_dataset(
            pool="hqs10p1", dataset="L1S4DAT1", system_id=hqs10.id
        )
        hqs7_snapshot_models = snapshot_repo.get_by_pool_dataset(
            pool="hqs7p1", dataset="L1S4DAT1", system_id=hqs7.id
        )

        # Extract midnight snapshot names
        hqs10_midnight_names = {
            comparison_service._extract_snapshot_name(s.name)
            for s in hqs10_snapshot_models
            if comparison_service._extract_snapshot_name(s.name).endswith("-000000")
        }
        hqs7_midnight_names = {
            comparison_service._extract_snapshot_name(s.name)
            for s in hqs7_snapshot_models
            if comparison_service._extract_snapshot_name(s.name).endswith("-000000")
        }

        # Test the validator function
        is_out_of_sync = is_snapshot_out_of_sync_by_24h(
            source_snapshots=hqs10_snapshot_models,
            target_snapshots=hqs7_snapshot_models,
            source_snapshot_names=hqs10_midnight_names,
            target_snapshot_names=hqs7_midnight_names,
            comparison_service=comparison_service,
        )

        # HQS7 is missing snapshots from 2025-11-05 onwards, so it should be out of sync
        # Latest HQS10: 2025-11-30-000000
        # Latest HQS7: 2025-11-04-000000
        # Time difference: 26 days = 624 hours > 24 hours
        assert is_out_of_sync, (
            "HQS7 should be detected as out of sync (missing snapshots from 2025-11-05 onwards, "
            "latest HQS10 snapshot is 2025-11-30, latest HQS7 is 2025-11-04, "
            f"26 days difference). is_out_of_sync returned: {is_out_of_sync}"
        )

        # Test the full sync instruction generation
        service = SyncCoordinationService(test_db)
        instructions = service.generate_dataset_sync_instructions(
            sync_group_id=sync_group.id,
            system_id=hqs10.id,  # HQS10 is the source
            incremental_only=True,
        )

        # Should detect that HQS7 needs to sync from HQS10
        assert instructions["dataset_count"] > 0, (
            f"Expected sync instructions for L1S4DAT1 dataset, but got {instructions['dataset_count']} datasets. "
            f"Instructions: {instructions}"
        )

        # Find the instruction for L1S4DAT1
        l1s4dat1_instruction = None
        for dataset in instructions["datasets"]:
            if dataset["dataset"] == "L1S4DAT1":
                l1s4dat1_instruction = dataset
                break

        assert l1s4dat1_instruction is not None, (
            f"No sync instruction found for L1S4DAT1 dataset. "
            f"Available datasets: {[d['dataset'] for d in instructions['datasets']]}"
        )

        # Verify the instruction details
        assert l1s4dat1_instruction["pool"] == "hqs10p1", "Source pool should be hqs10p1"
        assert l1s4dat1_instruction["target_pool"] == "hqs7p1", "Target pool should be hqs7p1"
        assert (
            l1s4dat1_instruction["ending_snapshot"] == "2025-11-30-000000"
        ), f"Ending snapshot should be 2025-11-30-000000, got {l1s4dat1_instruction['ending_snapshot']}"
        # Starting snapshot should be the most recent common snapshot (2025-11-04-000000)
        assert l1s4dat1_instruction["starting_snapshot"] == "2025-11-04-000000", (
            f"Starting snapshot should be 2025-11-04-000000 (most recent common), "
            f"got {l1s4dat1_instruction['starting_snapshot']}"
        )
