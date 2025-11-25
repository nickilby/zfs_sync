"""Unit tests for SnapshotComparisonService."""

from datetime import datetime, timedelta, timezone

import pytest

from zfs_sync.database.repositories import (
    SnapshotRepository,
    SystemRepository,
)
from zfs_sync.services.snapshot_comparison import SnapshotComparisonService


class TestSnapshotComparisonService:
    """Test suite for SnapshotComparisonService."""

    def test_compare_snapshots_by_dataset(self, test_db, sample_system_data, sample_snapshot_data):
        """Test comparing snapshots across systems by dataset."""
        # Create two systems
        system_repo = SystemRepository(test_db)
        system1 = system_repo.create(**sample_system_data)
        system2_data = sample_system_data.copy()
        system2_data["hostname"] = "test-system-2"
        system2 = system_repo.create(**system2_data)

        # Create snapshots
        snapshot_repo = SnapshotRepository(test_db)
        
        # System1 has snapshots
        snapshot1_data = sample_snapshot_data.copy()
        snapshot1_data["system_id"] = system1.id
        snapshot1 = snapshot_repo.create(**snapshot1_data)
        
        # System2 has same snapshot
        snapshot2_data = sample_snapshot_data.copy()
        snapshot2_data["system_id"] = system2.id
        snapshot2 = snapshot_repo.create(**snapshot2_data)

        # Compare
        service = SnapshotComparisonService(test_db)
        comparison = service.compare_snapshots_by_dataset(
            pool=sample_snapshot_data["pool"],
            dataset=sample_snapshot_data["dataset"],
            system_ids=[system1.id, system2.id],
        )

        assert "common_snapshots" in comparison
        assert "unique_snapshots" in comparison
        assert "missing_snapshots" in comparison
        assert len(comparison["common_snapshots"]) >= 1

    def test_find_snapshot_differences(self, test_db, sample_system_data, sample_snapshot_data):
        """Test finding differences between two systems."""
        # Create two systems
        system_repo = SystemRepository(test_db)
        system1 = system_repo.create(**sample_system_data)
        system2_data = sample_system_data.copy()
        system2_data["hostname"] = "test-system-2"
        system2 = system_repo.create(**system2_data)

        # Create snapshots - system1 has one, system2 has different one
        snapshot_repo = SnapshotRepository(test_db)
        
        snapshot1_data = sample_snapshot_data.copy()
        snapshot1_data["system_id"] = system1.id
        snapshot1 = snapshot_repo.create(**snapshot1_data)
        
        snapshot2_data = sample_snapshot_data.copy()
        snapshot2_data["system_id"] = system2.id
        snapshot2_data["name"] = "backup-20240116-120000"
        snapshot2 = snapshot_repo.create(**snapshot2_data)

        # Find differences
        service = SnapshotComparisonService(test_db)
        differences = service.find_snapshot_differences(
            system_id_1=system1.id,
            system_id_2=system2.id,
            pool=sample_snapshot_data["pool"],
            dataset=sample_snapshot_data["dataset"],
        )

        assert "only_in_system_1" in differences
        assert "only_in_system_2" in differences
        assert "in_both" in differences

    def test_get_snapshot_gaps(self, test_db, sample_system_data, sample_snapshot_data):
        """Test finding snapshot gaps."""
        # Create two systems
        system_repo = SystemRepository(test_db)
        system1 = system_repo.create(**sample_system_data)
        system2_data = sample_system_data.copy()
        system2_data["hostname"] = "test-system-2"
        system2 = system_repo.create(**system2_data)

        # Create snapshots - system1 has 3, system2 has 2 (missing middle one)
        snapshot_repo = SnapshotRepository(test_db)
        base_time = datetime.now(timezone.utc) - timedelta(days=3)
        
        for i in range(3):
            snapshot_data = sample_snapshot_data.copy()
            snapshot_data["system_id"] = system1.id
            snapshot_data["name"] = f"backup-202401{15+i:02d}-120000"
            snapshot_data["timestamp"] = base_time + timedelta(days=i)
            snapshot_repo.create(**snapshot_data)
        
        # System2 missing middle snapshot
        for i in [0, 2]:
            snapshot_data = sample_snapshot_data.copy()
            snapshot_data["system_id"] = system2.id
            snapshot_data["name"] = f"backup-202401{15+i:02d}-120000"
            snapshot_data["timestamp"] = base_time + timedelta(days=i)
            snapshot_repo.create(**snapshot_data)

        # Find gaps
        service = SnapshotComparisonService(test_db)
        gaps = service.get_snapshot_gaps(
            system_ids=[system1.id, system2.id],
            pool=sample_snapshot_data["pool"],
            dataset=sample_snapshot_data["dataset"],
        )

        assert isinstance(gaps, list)
        # Should find at least one gap (system2 missing snapshot 1)

