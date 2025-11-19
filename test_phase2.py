#!/usr/bin/env python3
"""Test script to verify Phase 2 setup."""

import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))

from zfs_sync.config import get_settings
from zfs_sync.database import create_engine, init_db
from zfs_sync.database.repositories import SystemRepository
from zfs_sync.logging_config import get_logger, setup_logging


def test_database():
    """Test database initialization and basic operations."""
    print("Testing database...")

    # Initialize database
    init_db()
    print("✓ Database initialized")

    # Test repository
    from zfs_sync.database import get_session

    db = get_session()
    try:
        repo = SystemRepository(db)
        print("✓ Repository pattern working")

        # Test create
        system = repo.create(
            hostname="test-system",
            platform="linux",
            connectivity_status="online",
        )
        print(f"✓ Created system: {system.hostname} ({system.id})")

        # Test get
        retrieved = repo.get(system.id)
        assert retrieved is not None, "System should be retrievable"
        print(f"✓ Retrieved system: {retrieved.hostname}")

        # Test get_by_hostname
        by_hostname = repo.get_by_hostname("test-system")
        assert by_hostname is not None, "System should be findable by hostname"
        print(f"✓ Found system by hostname: {by_hostname.hostname}")

        # Cleanup
        repo.delete(system.id)
        print("✓ Database operations working correctly")
    finally:
        db.close()


def test_api_imports():
    """Test that API components can be imported."""
    print("\nTesting API imports...")

    try:
        from zfs_sync.api import app
        print("✓ FastAPI app imported")

        from zfs_sync.api.routes import health, systems, snapshots, sync
        print("✓ API routes imported")

        # Check routes are registered
        routes = [route.path for route in app.routes]
        assert "/api/v1/health" in routes or "/health" in routes, "Health route should be registered"
        print("✓ API routes registered")
    except Exception as e:
        print(f"✗ API import error: {e}")
        raise


def test_logging():
    """Test logging configuration."""
    print("\nTesting logging...")

    setup_logging()
    logger = get_logger(__name__)
    logger.info("Test log message")
    print("✓ Logging system working")


if __name__ == "__main__":
    print("=" * 60)
    print("ZFS Sync - Phase 2 Setup Verification")
    print("=" * 60)
    print()

    try:
        settings = get_settings()
        print(f"Configuration loaded: {settings.app_name} v{settings.app_version}")
        print(f"Database URL: {settings.database_url}")
        print()

        test_database()
        test_api_imports()
        test_logging()

        print("\n" + "=" * 60)
        print("✓ Phase 2 setup complete and verified!")
        print("=" * 60)
        print("\nTo start the API server, run:")
        print("  python -m zfs_sync")
        print("  or")
        print("  uvicorn zfs_sync.api.app:app --reload")
    except Exception as e:
        print(f"\n✗ Error: {e}")
        import traceback

        traceback.print_exc()
        sys.exit(1)

