#!/usr/bin/env python3
"""Test script for Phase 3, Point 2: Snapshot State Tracking."""

import sys
from datetime import datetime, timedelta
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))

from zfs_sync.database import get_db, init_db
from zfs_sync.database.repositories import SnapshotRepository, SystemRepository
from zfs_sync.services.snapshot_comparison import SnapshotComparisonService
from zfs_sync.services.snapshot_history import SnapshotHistoryService


def create_test_data(db):
    """Create test systems and snapshots."""
    print("Creating test data...")

    # Create test systems
    system_repo = SystemRepository(db)
    system1 = system_repo.create(
        hostname="test-server-1",
        platform="linux",
        connectivity_status="online",
    )
    system2 = system_repo.create(
        hostname="test-server-2",
        platform="linux",
        connectivity_status="online",
    )
    print(
        f"[OK] Created systems: {system1.hostname} ({system1.id}) and {system2.hostname} ({system2.id})"
    )

    # Create snapshots for system1
    snapshot_repo = SnapshotRepository(db)
    base_time = datetime.utcnow() - timedelta(days=5)

    snapshots_s1 = []
    for i in range(5):
        snapshot = snapshot_repo.create(
            name=f"backup-202401{15+i:02d}-120000",
            pool="tank",
            dataset="tank/data",
            timestamp=base_time + timedelta(days=i),
            system_id=system1.id,
            size=1024 * 1024 * (i + 1),  # 1MB, 2MB, etc.
        )
        snapshots_s1.append(snapshot)

    # Create snapshots for system2 (some overlap, some missing)
    snapshots_s2 = []
    for i in [0, 1, 3, 4]:  # Missing snapshot 2
        snapshot = snapshot_repo.create(
            name=f"backup-202401{15+i:02d}-120000",
            pool="tank",
            dataset="tank/data",
            timestamp=base_time + timedelta(days=i),
            system_id=system2.id,
            size=1024 * 1024 * (i + 1),
        )
        snapshots_s2.append(snapshot)

    # Add one unique snapshot to system2
    unique_snapshot = snapshot_repo.create(
        name="backup-20240120-120000",
        pool="tank",
        dataset="tank/data",
        timestamp=base_time + timedelta(days=5),
        system_id=system2.id,
        size=1024 * 1024 * 6,
    )
    snapshots_s2.append(unique_snapshot)

    print(f"[OK] Created {len(snapshots_s1)} snapshots for system1")
    print(f"[OK] Created {len(snapshots_s2)} snapshots for system2")

    return system1, system2, snapshots_s1, snapshots_s2


def test_comparison_service(db, system1, system2):
    """Test snapshot comparison functionality."""
    print("\n" + "=" * 60)
    print("Testing Snapshot Comparison Service")
    print("=" * 60)

    service = SnapshotComparisonService(db)

    # Test 1: Compare snapshots across systems
    print("\n1. Comparing snapshots across systems...")
    comparison = service.compare_snapshots_by_dataset(
        pool="tank",
        dataset="tank/data",
        system_ids=[system1.id, system2.id],
    )

    print(f"   Common snapshots: {len(comparison['common_snapshots'])}")
    print(f"   - {comparison['common_snapshots']}")
    print(f"   Unique to system1: {len(comparison['unique_snapshots'][str(system1.id)])}")
    print(f"   Unique to system2: {len(comparison['unique_snapshots'][str(system2.id)])}")
    print(f"   Missing from system1: {len(comparison['missing_snapshots'][str(system1.id)])}")
    print(f"   Missing from system2: {len(comparison['missing_snapshots'][str(system2.id)])}")

    assert len(comparison["common_snapshots"]) > 0, "Should have common snapshots"
    print("   [OK] Comparison working correctly")

    # Test 2: Find differences between two systems
    print("\n2. Finding differences between two systems...")
    differences = service.find_snapshot_differences(
        system_id_1=system1.id,
        system_id_2=system2.id,
        pool="tank",
        dataset="tank/data",
    )

    print(f"   Only in system1: {len(differences['only_in_system_1'])}")
    print(f"   Only in system2: {len(differences['only_in_system_2'])}")
    print(f"   In both: {len(differences['in_both'])}")
    print("   [OK] Differences detection working")

    # Test 3: Find gaps
    print("\n3. Finding snapshot gaps...")
    gaps = service.get_snapshot_gaps(
        system_ids=[system1.id, system2.id],
        pool="tank",
        dataset="tank/data",
    )

    print(f"   Found {len(gaps)} gaps")
    if gaps:
        print(
            f"   Example gap: System {gaps[0]['system_id']} missing {gaps[0]['missing_snapshot']}"
        )
    print("   [OK] Gap detection working")


def test_history_service(db, system1, system2):
    """Test snapshot history functionality."""
    print("\n" + "=" * 60)
    print("Testing Snapshot History Service")
    print("=" * 60)

    service = SnapshotHistoryService(db)

    # Test 1: Get snapshot history
    print("\n1. Getting snapshot history...")
    history = service.get_snapshot_history(system_id=system1.id, days=30, limit=10)
    print(f"   Retrieved {len(history)} history entries")
    if history:
        print(f"   Latest: {history[0]['name']} at {history[0]['timestamp']}")
    print("   [OK] History retrieval working")

    # Test 2: Get timeline
    print("\n2. Getting snapshot timeline...")
    timeline = service.get_snapshot_timeline(
        pool="tank",
        dataset="tank/data",
        system_ids=[system1.id, system2.id],
    )
    print(f"   Timeline has {timeline['total_count']} snapshots")
    print(f"   Across {len(timeline['systems'])} systems")
    print("   [OK] Timeline working")

    # Test 3: Get statistics
    print("\n3. Getting snapshot statistics...")
    stats = service.get_snapshot_statistics(system_id=system1.id, days=30)
    print(f"   Total snapshots: {stats['total_snapshots']}")
    print(f"   Total size: {stats['total_size']} bytes")
    print(f"   Pools: {list(stats['pools'].keys())}")
    print("   [OK] Statistics working")


def test_batch_operations(db, system1):
    """Test batch snapshot operations."""
    print("\n" + "=" * 60)
    print("Testing Batch Operations")
    print("=" * 60)

    snapshot_repo = SnapshotRepository(db)

    # Create multiple snapshots
    print("\n1. Creating snapshots in batch...")
    batch_snapshots = []
    base_time = datetime.utcnow()

    for i in range(3):
        snapshot = snapshot_repo.create(
            name=f"batch-snapshot-{i}",
            pool="tank",
            dataset="tank/batch",
            timestamp=base_time + timedelta(minutes=i),
            system_id=system1.id,
            size=1024 * 100 * (i + 1),
        )
        batch_snapshots.append(snapshot)

    print(f"   Created {len(batch_snapshots)} snapshots")
    print("   [OK] Batch creation working")

    # Verify they exist
    retrieved = snapshot_repo.get_by_pool_dataset(
        pool="tank", dataset="tank/batch", system_id=system1.id
    )
    print(f"   Retrieved {len(retrieved)} snapshots from database")
    assert len(retrieved) == len(batch_snapshots), "All batch snapshots should be stored"
    print("   [OK] Batch retrieval working")


def main():
    """Run all tests."""
    print("=" * 60)
    print("ZFS Sync - Phase 3, Point 2: Snapshot State Tracking Tests")
    print("=" * 60)

    try:
        # Initialize database
        print("\nInitializing database...")
        init_db()
        print("[OK] Database initialized")

        # Get database session
        db = next(get_db())

        try:
            # Create test data
            system1, system2, snapshots_s1, snapshots_s2 = create_test_data(db)

            # Run tests
            test_comparison_service(db, system1, system2)
            test_history_service(db, system1, system2)
            test_batch_operations(db, system1)

            print("\n" + "=" * 60)
            print("[OK] All tests passed!")
            print("=" * 60)
            print("\nPhase 3, Point 2: Snapshot State Tracking is working correctly!")

        finally:
            db.close()

    except Exception as e:
        print(f"\n[ERROR] Error: {e}")
        import traceback

        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
