#!/usr/bin/env python3
"""Simple test script to verify Phase 1 setup."""

from zfs_sync.config import get_settings
from zfs_sync.models import System, Snapshot, SyncGroup, SyncState, SyncStatus


def test_models():
    """Test that all models can be instantiated."""
    print("Testing data models...")

    # Test System model
    system = System(
        hostname="test-server",
        platform="linux",
        connectivity_status="online",
    )
    print(f"✓ System model: {system.hostname} ({system.id})")

    # Test Snapshot model
    from datetime import datetime

    snapshot = Snapshot(
        name="test-snapshot",
        pool="tank",
        dataset="tank/data",
        timestamp=datetime.now(),
        system_id=system.id,
    )
    print(f"✓ Snapshot model: {snapshot.name} on {snapshot.pool}/{snapshot.dataset}")

    # Test SyncGroup model
    sync_group = SyncGroup(
        name="test-group",
        system_ids=[system.id],
    )
    print(f"✓ SyncGroup model: {sync_group.name} with {len(sync_group.system_ids)} system(s)")

    # Test SyncState model
    sync_state = SyncState(
        sync_group_id=sync_group.id,
        snapshot_id=snapshot.id,
        system_ids=[system.id],
        status=SyncStatus.IN_SYNC,
    )
    print(f"✓ SyncState model: {sync_state.status}")

    print("\nAll models working correctly!")


def test_config():
    """Test configuration system."""
    print("\nTesting configuration system...")

    settings = get_settings()
    print(f"✓ Settings loaded: {settings.app_name} v{settings.app_version}")
    print(f"  - Host: {settings.host}:{settings.port}")
    print(f"  - Database: {settings.database_url}")
    print(f"  - Log level: {settings.log_level}")
    print(f"  - Sync interval: {settings.default_sync_interval_seconds}s")

    print("\nConfiguration system working correctly!")


if __name__ == "__main__":
    print("=" * 50)
    print("ZFS Sync - Phase 1 Setup Verification")
    print("=" * 50)
    print()

    try:
        test_models()
        test_config()
        print("\n" + "=" * 50)
        print("✓ Phase 1 setup complete and verified!")
        print("=" * 50)
    except Exception as e:
        print(f"\n✗ Error: {e}")
        import traceback

        traceback.print_exc()
        exit(1)
