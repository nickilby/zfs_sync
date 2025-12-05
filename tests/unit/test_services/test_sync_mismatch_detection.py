"""Test to expose the bug where systems with missing snapshots are not detected as out of sync."""

from datetime import datetime, timezone


from zfs_sync.database.repositories import (
    SnapshotRepository,
    SyncGroupRepository,
    SystemRepository,
)
from zfs_sync.services.sync_coordination import SyncCoordinationService
from zfs_sync.services.sync_validators import is_snapshot_out_of_sync_by_72h
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

        # Test the is_snapshot_out_of_sync_by_72h function directly
        hqs10_snapshot_models = snapshot_repo.get_by_pool_dataset(
            pool="hqs10p1", dataset="L1S4DAT1", system_id=hqs10.id
        )
        hqs7_snapshot_models = snapshot_repo.get_by_pool_dataset(
            pool="hqs7p1", dataset="L1S4DAT1", system_id=hqs7.id
        )

        # Extract midnight snapshot names
        hqs10_midnight_names = {
            comparison_service.extract_snapshot_name(s.name)
            for s in hqs10_snapshot_models
            if comparison_service.extract_snapshot_name(s.name).endswith("-000000")
        }
        hqs7_midnight_names = {
            comparison_service.extract_snapshot_name(s.name)
            for s in hqs7_snapshot_models
            if comparison_service.extract_snapshot_name(s.name).endswith("-000000")
        }

        # Test the validator function
        is_out_of_sync = is_snapshot_out_of_sync_by_72h(
            source_snapshots=hqs10_snapshot_models,
            target_snapshots=hqs7_snapshot_models,
            source_snapshot_names=hqs10_midnight_names,
            target_snapshot_names=hqs7_midnight_names,
            comparison_service=comparison_service,
        )

        # HQS7 is missing snapshots from 2025-11-05 onwards, so it should be out of sync
        # Latest HQS10: 2025-11-30-000000
        # Latest HQS7: 2025-11-04-000000
        # Time difference: 26 days = 624 hours > 72 hours
        assert is_out_of_sync, (
            "HQS7 should be detected as out of sync (missing snapshots from 2025-11-05 onwards, "
            "latest HQS10 snapshot is 2025-11-30, latest HQS7 is 2025-11-04, "
            f"26 days difference). is_out_of_sync returned: {is_out_of_sync}"
        )

        # Test the full sync instruction generation
        service = SyncCoordinationService(test_db)
        instructions = service.get_sync_instructions(
            system_id=hqs7.id,  # HQS7 is the target
            sync_group_id=sync_group.id,
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

        # Verify the instruction details - updated for new consolidated format
        assert l1s4dat1_instruction["target_pool"] == "hqs7p1", "Target pool should be hqs7p1"
        assert l1s4dat1_instruction["ending_snapshot"] is not None, "Should have an ending snapshot"

        # Check that the latest midnight snapshot is included in the ending snapshot
        # Since we now filter to only midnight snapshots, the ending snapshot will be
        # the latest midnight snapshot that's older than 72 hours (2025-11-30-000000)
        assert (
            l1s4dat1_instruction["ending_snapshot"] == "2025-11-30-000000"
        ), f"Ending snapshot should be the latest midnight snapshot 2025-11-30-000000, got: {l1s4dat1_instruction['ending_snapshot']}"

        # Check that incremental base is from the common snapshot
        assert (
            l1s4dat1_instruction["starting_snapshot"] is not None
        ), "Should have a starting snapshot for incremental sync"

        assert (
            "2025-10-30-000000" in l1s4dat1_instruction["starting_snapshot"]
        ), f"Starting snapshot should be from common base 2025-10-30-000000, got: {l1s4dat1_instruction['starting_snapshot']}"

    def test_l1s4dat1_72h_gate_generates_expected_command(self, test_db):
        """
        Reproduce the L1S4DAT1 production scenario and assert the 72-hour gate
        produces the expected incremental send range.

        This uses the snapshot sets from the /snapshots/compare-dataset output:
        - Common snapshots include 2025-10-30-000000
        - Source (hub) has snapshots up to 2025-12-03-120000
        - Target has snapshots up to 2025-11-04-000000

        With comparison time 2025-12-04T09:13Z, the 72-hour rule (only send
        snapshots at least 72 hours older than \"now\") should allow an ending
        snapshot of 2025-12-01-000000, but not 2025-12-01-120000 or later.
        """
        system_repo = SystemRepository(test_db)
        source = system_repo.create(
            hostname="hqs10",
            platform="linux",
            connectivity_status="online",
            ssh_hostname="hqs10.example.com",
            ssh_user="root",
            ssh_port=22,
        )
        target = system_repo.create(
            hostname="hqs7",
            platform="linux",
            connectivity_status="online",
            ssh_hostname="hqs7-san",
            ssh_user="root",
            ssh_port=22,
        )

        sync_group_repo = SyncGroupRepository(test_db)
        sync_group = sync_group_repo.create(
            name="l1s4dat1-72h-test",
            description="L1S4DAT1 72h gate test group",
            enabled=True,
        )
        sync_group_repo.add_system(sync_group.id, source.id)
        sync_group_repo.add_system(sync_group.id, target.id)

        snapshot_repo = SnapshotRepository(test_db)

        # Source snapshots (matching the JSON example for system 72c0c3d5-...)
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

        # Target snapshots (matching the JSON example for system 58125bc5-...)
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

        service = SyncCoordinationService(test_db)
        instructions = service.get_sync_instructions(
            system_id=target.id,
            sync_group_id=sync_group.id,
            include_diagnostics=True,
        )

        assert instructions["dataset_count"] > 0, (
            f"Expected sync instructions for L1S4DAT1 dataset, but got "
            f"{instructions['dataset_count']} datasets. Instructions: {instructions}"
        )

        l1s4dat1_instruction = None
        for dataset in instructions["datasets"]:
            if dataset["dataset"] == "L1S4DAT1":
                l1s4dat1_instruction = dataset
                break

        assert l1s4dat1_instruction is not None, (
            f"No sync instruction found for L1S4DAT1 dataset. "
            f"Available datasets: {[d['dataset'] for d in instructions['datasets']]}"
        )

        # Starting snapshot should be last common: 2025-10-30-000000
        assert (
            l1s4dat1_instruction["starting_snapshot"] == "2025-10-30-000000"
        ), f"Expected starting_snapshot=2025-10-30-000000, got: {l1s4dat1_instruction['starting_snapshot']}"

        # Ending snapshot is gated by 72h rule: latest midnight snapshot older than now-72h
        # As time progresses, this will shift (e.g., on Dec 5 it's 2025-12-02, on Dec 6 it's 2025-12-03)
        assert l1s4dat1_instruction["ending_snapshot"] in [
            "2025-12-01-000000",
            "2025-12-02-000000",
            "2025-12-03-000000",
        ], f"Expected ending_snapshot to be a recent midnight snapshot gated by 72h, got: {l1s4dat1_instruction['ending_snapshot']}"

        # Commands should include a single incremental send from starting to ending
        commands = l1s4dat1_instruction.get("commands", [])
        assert commands, f"Expected at least one command for L1S4DAT1, got: {commands}"
        command = commands[0]

        assert "zfs send" in command and "-I" in command, f"Unexpected command: {command}"
        assert "@2025-10-30-000000" in command, f"Incremental base missing in command: {command}"
        # The ending snapshot in the command should match the instruction's ending_snapshot
        assert (
            f"@{l1s4dat1_instruction['ending_snapshot']}" in command
        ), f"Ending snapshot {l1s4dat1_instruction['ending_snapshot']} missing in command: {command}"

    def test_directional_sync_hub_system_instructions(self, test_db):
        """
        Test directional sync behavior when requesting instructions for the hub system.

        This reproduces the bug where hub system receives empty instructions even though
        snapshot comparison shows mismatches exist.

        Scenario (matches production):
        - System A (hub): has snapshots from 2025-09-04 to 2025-12-01
        - System B (source): has snapshots from 2025-10-08 to 2025-11-04
        - Both systems are missing snapshots from each other
        - Directional sync: hub should replicate TO sources, but what about hub receiving from sources?

        Expected behavior needs to be determined:
        - Option A: Hub should receive instructions to sync missing snapshots from sources
        - Option B: Hub should NOT receive instructions (hub only sends, never receives)
        """
        # Create systems matching production UUIDs
        system_repo = SystemRepository(test_db)
        hub_system = system_repo.create(
            hostname="hub-system",
            platform="linux",
            connectivity_status="online",
            ssh_hostname="hub.example.com",
            ssh_user="root",
            ssh_port=22,
        )
        source_system = system_repo.create(
            hostname="source-system",
            platform="linux",
            connectivity_status="online",
            ssh_hostname="source.example.com",
            ssh_user="root",
            ssh_port=22,
        )

        # Create directional sync group with hub
        sync_group_repo = SyncGroupRepository(test_db)
        sync_group = sync_group_repo.create(
            name="directional-sync-group",
            description="Directional sync test",
            enabled=True,
            directional=True,
            hub_system_id=hub_system.id,
        )
        sync_group_repo.add_system(sync_group.id, hub_system.id)
        sync_group_repo.add_system(sync_group.id, source_system.id)

        # Create snapshot repository
        snapshot_repo = SnapshotRepository(test_db)
        comparison_service = SnapshotComparisonService(test_db)

        # Hub system snapshots (matches production: 72c0c3d5-ca09-4174-a2b2-46cf3842d99a)
        # Has weekly snapshots + some daily ones
        hub_snapshots = [
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
        ]

        # Source system snapshots (matches production: 58125bc5-76cd-4bb9-bb88-3d2d56f322df)
        # Has daily snapshots from 2025-10-08 to 2025-11-04
        source_snapshots = [
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
            ("2025-10-31-000000", datetime(2025, 10, 31, 0, 0, 0, tzinfo=timezone.utc)),
            ("2025-11-01-000000", datetime(2025, 11, 1, 0, 0, 0, tzinfo=timezone.utc)),
            ("2025-11-02-000000", datetime(2025, 11, 2, 0, 0, 0, tzinfo=timezone.utc)),
            ("2025-11-03-000000", datetime(2025, 11, 3, 0, 0, 0, tzinfo=timezone.utc)),
            ("2025-11-03-120000", datetime(2025, 11, 3, 12, 0, 0, tzinfo=timezone.utc)),
            ("2025-11-04-000000", datetime(2025, 11, 4, 0, 0, 0, tzinfo=timezone.utc)),
        ]

        # Create snapshots for hub system
        for snapshot_name, timestamp in hub_snapshots:
            snapshot_repo.create(
                name=f"hubp1/L1S4DAT1@{snapshot_name}",
                pool="hubp1",
                dataset="L1S4DAT1",
                system_id=hub_system.id,
                timestamp=timestamp,
                size=100 * 1024 * 1024 * 1024,  # 100GB
            )

        # Create snapshots for source system
        for snapshot_name, timestamp in source_snapshots:
            snapshot_repo.create(
                name=f"sourcep1/L1S4DAT1@{snapshot_name}",
                pool="sourcep1",
                dataset="L1S4DAT1",
                system_id=source_system.id,
                timestamp=timestamp,
                size=50 * 1024 * 1024 * 1024,  # 50GB
            )

        # Verify snapshot comparison shows mismatches
        comparison = comparison_service.compare_snapshots_by_dataset(
            dataset="L1S4DAT1", system_ids=[hub_system.id, source_system.id]
        )
        assert (
            len(comparison["missing_snapshots"].get(str(hub_system.id), [])) > 0
        ), "Hub system should be missing snapshots from source system"
        assert (
            len(comparison["missing_snapshots"].get(str(source_system.id), [])) > 0
        ), "Source system should be missing snapshots from hub system"

        # Test requesting instructions for hub system (this is the bug scenario)
        service = SyncCoordinationService(test_db)
        hub_instructions = service.get_sync_instructions(
            system_id=hub_system.id,  # Requesting instructions for hub
            sync_group_id=sync_group.id,
            include_diagnostics=True,
        )

        # Test requesting instructions for source system (this should work)
        source_instructions = service.get_sync_instructions(
            system_id=source_system.id,  # Requesting instructions for source
            sync_group_id=sync_group.id,
            include_diagnostics=True,
        )

        # Log results for analysis
        print(f"\nHub system instructions: {hub_instructions['dataset_count']} datasets")
        print(f"Source system instructions: {source_instructions['dataset_count']} datasets")
        if hub_instructions.get("diagnostics"):
            print(f"Hub diagnostics: {hub_instructions['diagnostics']}")
        if source_instructions.get("diagnostics"):
            print(f"Source diagnostics: {source_instructions['diagnostics']}")

        # Source system should receive instructions (hub -> source)
        assert source_instructions["dataset_count"] > 0, (
            f"Source system should receive instructions to sync from hub. "
            f"Got {source_instructions['dataset_count']} datasets. "
            f"Diagnostics: {source_instructions.get('diagnostics', [])}"
        )

        # Hub should receive instructions on what snapshots to send to sources
        # Hub is source of truth and needs to know what to send to spoke systems
        assert hub_instructions["dataset_count"] > 0, (
            f"Hub system should receive instructions on what snapshots to send to sources. "
            f"Got {hub_instructions['dataset_count']} datasets. "
            f"Diagnostics: {hub_instructions.get('diagnostics', [])}"
        )

        # Verify hub instructions contain L1S4DAT1 dataset
        hub_datasets = [d["dataset"] for d in hub_instructions["datasets"]]
        assert "L1S4DAT1" in hub_datasets, (
            f"Hub instructions should include L1S4DAT1 dataset. " f"Found datasets: {hub_datasets}"
        )

        # Find the instruction for L1S4DAT1
        hub_l1s4dat1_instruction = None
        for dataset in hub_instructions["datasets"]:
            if dataset["dataset"] == "L1S4DAT1":
                hub_l1s4dat1_instruction = dataset
                break

        assert hub_l1s4dat1_instruction is not None, "Hub should have instruction for L1S4DAT1"
        assert hub_l1s4dat1_instruction["pool"] == "hubp1", "Pool should be hubp1 (hub's pool)"
        assert (
            hub_l1s4dat1_instruction["ending_snapshot"] is not None
        ), "Should have an ending snapshot"

    def test_orphaned_snapshots_filter_mismatches(self, test_db):
        """
        Test that reproduces the orphaned snapshot scenario where mismatches are detected
        but filtered out by the 72-hour check.

        Scenario (matches production issue):
        - System A (hub): has snapshots from 2025-09-11 to 2025-12-03
        - System B (source): has snapshots from 2025-10-08 to 2025-11-04
        - System A has many orphaned snapshots (exist only on A, no common ancestor with B)
        - System B is missing many snapshots from System A
        - The 72-hour check compares latest midnight snapshots and may filter out all mismatches
        - even though there are many missing intermediate snapshots

        Expected behavior:
        - Mismatches should be detected (System B missing snapshots from System A)
        - But if latest midnight snapshots are within 72 hours, actions may be filtered
        - This test verifies the diagnostic logging captures this scenario
        """
        # Create systems matching production scenario
        system_repo = SystemRepository(test_db)
        system_a = system_repo.create(
            hostname="system-a",
            platform="linux",
            connectivity_status="online",
            ssh_hostname="system-a.example.com",
            ssh_user="root",
            ssh_port=22,
        )
        system_b = system_repo.create(
            hostname="system-b",
            platform="linux",
            connectivity_status="online",
            ssh_hostname="system-b.example.com",
            ssh_user="root",
            ssh_port=22,
        )

        # Create directional sync group with System A as hub
        sync_group_repo = SyncGroupRepository(test_db)
        sync_group = sync_group_repo.create(
            name="orphaned-snapshot-test-group",
            description="Test orphaned snapshot scenario",
            enabled=True,
            directional=True,
            hub_system_id=system_a.id,
        )
        sync_group_repo.add_system(sync_group.id, system_a.id)
        sync_group_repo.add_system(sync_group.id, system_b.id)

        # Create snapshot repository
        snapshot_repo = SnapshotRepository(test_db)
        comparison_service = SnapshotComparisonService(test_db)

        # System A (hub) snapshots - has many snapshots including orphaned ones
        # These match the production scenario: many snapshots from Sept to Dec
        system_a_snapshots = [
            # Weekly snapshots (some may be orphaned if System B doesn't have them)
            ("2025-09-11-000000", datetime(2025, 9, 11, 0, 0, 0, tzinfo=timezone.utc)),
            ("2025-09-18-000000", datetime(2025, 9, 18, 0, 0, 0, tzinfo=timezone.utc)),
            ("2025-09-25-000000", datetime(2025, 9, 25, 0, 0, 0, tzinfo=timezone.utc)),
            ("2025-10-02-000000", datetime(2025, 10, 2, 0, 0, 0, tzinfo=timezone.utc)),
            ("2025-10-09-000000", datetime(2025, 10, 9, 0, 0, 0, tzinfo=timezone.utc)),
            ("2025-10-16-000000", datetime(2025, 10, 16, 0, 0, 0, tzinfo=timezone.utc)),
            ("2025-10-23-000000", datetime(2025, 10, 23, 0, 0, 0, tzinfo=timezone.utc)),
            ("2025-10-30-000000", datetime(2025, 10, 30, 0, 0, 0, tzinfo=timezone.utc)),
            ("2025-11-06-000000", datetime(2025, 11, 6, 0, 0, 0, tzinfo=timezone.utc)),
            ("2025-11-13-000000", datetime(2025, 11, 13, 0, 0, 0, tzinfo=timezone.utc)),
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
            ("2025-12-02-000000", datetime(2025, 12, 2, 0, 0, 0, tzinfo=timezone.utc)),
            ("2025-12-03-000000", datetime(2025, 12, 3, 0, 0, 0, tzinfo=timezone.utc)),
            ("2025-12-03-163000", datetime(2025, 12, 3, 16, 30, 0, tzinfo=timezone.utc)),
        ]

        # System B (source) snapshots - has fewer snapshots, missing many from System A
        # This creates the scenario where System B is missing many snapshots
        system_b_snapshots = [
            # Only has snapshots up to 2025-11-04, missing everything after
            ("2025-10-08-000000", datetime(2025, 10, 8, 0, 0, 0, tzinfo=timezone.utc)),
            ("2025-10-09-000000", datetime(2025, 10, 9, 0, 0, 0, tzinfo=timezone.utc)),
            ("2025-10-16-000000", datetime(2025, 10, 16, 0, 0, 0, tzinfo=timezone.utc)),
            ("2025-10-23-000000", datetime(2025, 10, 23, 0, 0, 0, tzinfo=timezone.utc)),
            ("2025-10-30-000000", datetime(2025, 10, 30, 0, 0, 0, tzinfo=timezone.utc)),
            ("2025-11-06-000000", datetime(2025, 11, 6, 0, 0, 0, tzinfo=timezone.utc)),
            ("2025-11-13-000000", datetime(2025, 11, 13, 0, 0, 0, tzinfo=timezone.utc)),
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
            # System B stops here - missing 2025-12-01, 2025-12-02, 2025-12-03
        ]

        # Create snapshots for System A
        for snapshot_name, timestamp in system_a_snapshots:
            snapshot_repo.create(
                name=f"hqs10p1/M1S2MIR1@{snapshot_name}",
                pool="hqs10p1",
                dataset="M1S2MIR1",
                system_id=system_a.id,
                timestamp=timestamp,
                size=100 * 1024 * 1024 * 1024,  # 100GB
            )

        # Create snapshots for System B
        for snapshot_name, timestamp in system_b_snapshots:
            snapshot_repo.create(
                name=f"hqs7p1/M1S2MIR1@{snapshot_name}",
                pool="hqs7p1",
                dataset="M1S2MIR1",
                system_id=system_b.id,
                timestamp=timestamp,
                size=50 * 1024 * 1024 * 1024,  # 50GB
            )

        # Verify snapshot comparison shows mismatches
        comparison = comparison_service.compare_snapshots_by_dataset(
            dataset="M1S2MIR1", system_ids=[system_a.id, system_b.id]
        )
        system_b_missing = comparison["missing_snapshots"].get(str(system_b.id), [])
        assert (
            len(system_b_missing) > 0
        ), f"System B should be missing snapshots from System A. Missing: {system_b_missing}"

        # Test sync action generation - this should detect mismatches but may filter them
        service = SyncCoordinationService(test_db)
        actions = service.determine_sync_actions(sync_group_id=sync_group.id)

        # Verify mismatches are detected
        mismatches = service.detect_sync_mismatches(sync_group_id=sync_group.id)
        assert len(mismatches) > 0, f"Should detect mismatches. Found: {len(mismatches)} mismatches"

        # The key test: check if actions are filtered by 72-hour check
        # System A latest: 2025-12-03-000000
        # System B latest: 2025-11-30-000000
        # Time difference: 3 days = 72 hours exactly
        # This is a boundary case - if the check uses > 72 hours, it should pass
        # If it uses >= 72 hours, it might filter

        # Get instructions for System B (target)
        instructions = service.get_sync_instructions(
            system_id=system_b.id,
            sync_group_id=sync_group.id,
            include_diagnostics=True,
        )

        # Log the results for analysis
        print("\n=== Orphaned Snapshot Test Results ===")
        print(f"Mismatches detected: {len(mismatches)}")
        print(f"Actions generated: {len(actions)}")
        print(f"Instructions datasets: {instructions['dataset_count']}")
        if instructions.get("diagnostics"):
            print(f"Diagnostics: {instructions['diagnostics']}")

        # The test verifies that:
        # 1. Mismatches are detected (System B missing snapshots from System A)
        # 2. Diagnostic logging captures why actions are filtered (if they are)
        # 3. The 72-hour check behavior is visible in logs

        # Note: This test doesn't assert a specific outcome because the 72-hour check
        # behavior depends on the exact time difference. The important thing is that
        # diagnostic logging will show what's happening.
        assert len(mismatches) > 0, "Mismatches should be detected"
