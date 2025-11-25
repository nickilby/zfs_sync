"""Unit tests for ConflictResolutionService."""

from datetime import datetime, timedelta, timezone
from uuid import uuid4


from zfs_sync.database.repositories import (
    SnapshotRepository,
    SyncGroupRepository,
    SystemRepository,
)
from zfs_sync.services.conflict_resolution import (
    ConflictResolutionService,
    ConflictResolutionStrategy,
)


class TestConflictResolutionService:
    """Test suite for ConflictResolutionService."""

    def test_detect_timestamp_mismatch(self, test_db, sample_system_data, sample_snapshot_data):
        """Test detection of timestamp mismatches."""
        # Create two systems
        system_repo = SystemRepository(test_db)
        system1 = system_repo.create(**sample_system_data)
        system2_data = sample_system_data.copy()
        system2_data["hostname"] = "test-system-2"
        system2 = system_repo.create(**system2_data)

        # Create sync group
        sync_group_repo = SyncGroupRepository(test_db)
        sync_group = sync_group_repo.create(
            name="test-group",
            description="Test group",
        )
        sync_group_repo.add_system(sync_group.id, system1.id)
        sync_group_repo.add_system(sync_group.id, system2.id)

        # Create snapshots with same name but different timestamps
        snapshot_repo = SnapshotRepository(test_db)
        snapshot1_data = sample_snapshot_data.copy()
        snapshot1_data["system_id"] = system1.id
        snapshot_repo.create(**snapshot1_data)

        snapshot2_data = sample_snapshot_data.copy()
        snapshot2_data["system_id"] = system2.id
        snapshot2_data["timestamp"] = datetime.now(timezone.utc) + timedelta(hours=1)
        snapshot_repo.create(**snapshot2_data)

        # Detect conflicts
        service = ConflictResolutionService(test_db)
        conflicts = service.detect_conflicts(
            sync_group.id, sample_snapshot_data["pool"], sample_snapshot_data["dataset"]
        )

        # Should detect timestamp mismatch
        assert len(conflicts) > 0
        timestamp_conflicts = [
            c for c in conflicts if c["type"] == "timestamp_mismatch"
        ]
        assert len(timestamp_conflicts) > 0

    def test_resolve_conflict_use_newest(self, test_db):
        """Test conflict resolution using newest strategy."""
        # Create conflict data
        conflict = {
            "type": "timestamp_mismatch",
            "snapshot_name": "backup-20240115-120000",
            "pool": "tank",
            "dataset": "tank/data",
            "sync_group_id": str(uuid4()),
            "systems": {
                str(uuid4()): {
                    "timestamp": (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat(),
                    "size": 1024,
                    "snapshot_id": str(uuid4()),
                },
                str(uuid4()): {
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "size": 2048,
                    "snapshot_id": str(uuid4()),
                },
            },
            "severity": "medium",
            "detected_at": datetime.now(timezone.utc).isoformat(),
        }

        service = ConflictResolutionService(test_db)
        result = service.resolve_conflict(
            conflict=conflict,
            strategy=ConflictResolutionStrategy.USE_NEWEST,
        )

        assert result["status"] == "resolved"
        assert result["strategy"] == "use_newest"
        assert "actions" in result
        assert len(result["actions"]) > 0

    def test_resolve_conflict_manual(self, test_db):
        """Test conflict resolution requiring manual intervention."""
        conflict = {
            "type": "divergent_snapshots",
            "snapshot_name": "backup-20240115-120000",
            "pool": "tank",
            "dataset": "tank/data",
            "sync_group_id": str(uuid4()),
            "systems": {
                str(uuid4()): {
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "size": 1024,
                    "snapshot_id": str(uuid4()),
                },
            },
            "severity": "high",
            "detected_at": datetime.now(timezone.utc).isoformat(),
        }

        service = ConflictResolutionService(test_db)
        result = service.resolve_conflict(
            conflict=conflict,
            strategy=ConflictResolutionStrategy.MANUAL,
        )

        assert result["status"] == "requires_manual_intervention"
        assert "message" in result

    def test_resolve_conflict_ignore(self, test_db):
        """Test ignoring a conflict."""
        conflict = {
            "type": "size_mismatch",
            "snapshot_name": "backup-20240115-120000",
            "pool": "tank",
            "dataset": "tank/data",
            "sync_group_id": str(uuid4()),
            "systems": {},
            "severity": "low",
            "detected_at": datetime.now(timezone.utc).isoformat(),
        }

        service = ConflictResolutionService(test_db)
        result = service.resolve_conflict(
            conflict=conflict,
            strategy=ConflictResolutionStrategy.IGNORE,
        )

        assert result["status"] == "ignored"

    def test_get_all_conflicts(self, test_db, sample_system_data):
        """Test getting all conflicts for a sync group."""
        # Create systems and sync group
        system_repo = SystemRepository(test_db)
        system1 = system_repo.create(**sample_system_data)
        system2_data = sample_system_data.copy()
        system2_data["hostname"] = "test-system-2"
        system2 = system_repo.create(**system2_data)

        sync_group_repo = SyncGroupRepository(test_db)
        sync_group = sync_group_repo.create(
            name="test-group",
            description="Test group",
        )
        sync_group_repo.add_system(sync_group.id, system1.id)
        sync_group_repo.add_system(sync_group.id, system2.id)

        service = ConflictResolutionService(test_db)
        conflicts = service.get_all_conflicts(sync_group.id)

        # Should return a list (may be empty if no conflicts)
        assert isinstance(conflicts, list)

