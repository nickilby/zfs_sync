"""Pytest configuration and shared fixtures."""

import os
import tempfile
from typing import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import Session, sessionmaker

from zfs_sync.api.app import app
from zfs_sync.database.base import Base, get_db

# Import models to ensure they register with Base.metadata
import zfs_sync.database.models  # noqa: F401

# Use file-based SQLite for tests to ensure consistent database across connections
# In-memory SQLite creates separate databases per connection, causing test failures
_test_db_file = tempfile.NamedTemporaryFile(delete=False, suffix=".db")
_test_db_file.close()
TEST_DATABASE_URL = f"sqlite:///{_test_db_file.name}"


@pytest.fixture(scope="session", autouse=True)
def verify_database_setup():
    """Autouse fixture to verify database models are properly registered."""
    # This runs once per test session before any tests
    # Verify that models are imported and registered with Base.metadata
    expected_tables = {
        "systems",
        "snapshots",
        "sync_groups",
        "sync_group_systems",
        "sync_states",
    }

    # Check that all expected tables are in Base.metadata
    registered_tables = set(Base.metadata.tables.keys())
    missing_tables = expected_tables - registered_tables

    if missing_tables:
        raise RuntimeError(
            f"Database models not properly registered. Missing tables in metadata: {missing_tables}. "
            f"Registered tables: {registered_tables}. "
            f"This usually means models weren't imported before Base.metadata was accessed."
        )

    yield  # Continue with tests


def verify_tables_exist(engine) -> None:
    """Verify that all expected tables exist in the database."""
    inspector = inspect(engine)
    existing_tables = set(inspector.get_table_names())

    # Expected tables based on models
    expected_tables = {
        "systems",
        "snapshots",
        "sync_groups",
        "sync_group_systems",
        "sync_states",
    }

    missing_tables = expected_tables - existing_tables
    if missing_tables:
        raise RuntimeError(
            f"Missing database tables: {missing_tables}. "
            f"Existing tables: {existing_tables}. "
            f"This indicates a problem with database initialization."
        )


@pytest.fixture(scope="function")
def test_db() -> Generator[Session, None, None]:
    """Create a test database session with in-memory SQLite."""
    # Create a new engine for testing
    engine = create_engine(
        TEST_DATABASE_URL,
        connect_args={"check_same_thread": False},
        echo=False,
    )

    # Models are already imported at module level, create all tables
    Base.metadata.create_all(bind=engine)

    # Verify tables were created successfully
    verify_tables_exist(engine)

    # Create a session
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    session = TestingSessionLocal()

    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=engine)
        engine.dispose()
        # Clean up test database file
        import os

        if os.path.exists(_test_db_file.name):
            os.unlink(_test_db_file.name)


@pytest.fixture(scope="function")
def test_client(test_db: Session) -> Generator[TestClient, None, None]:
    """Create a test client with overridden database dependency."""
    # Get engine from session using get_bind() method
    # test_db fixture already verified tables exist, but double-check here
    try:
        engine = test_db.get_bind()
        verify_tables_exist(engine)
    except AttributeError:
        # If get_bind() doesn't exist, skip verification
        # test_db fixture already verified tables exist
        pass

    # Override the get_db dependency BEFORE creating TestClient
    def override_get_db():
        try:
            yield test_db
        finally:
            pass  # Don't close the session here, let test_db fixture handle it

    app.dependency_overrides[get_db] = override_get_db

    # TestClient doesn't trigger startup events by default in FastAPI
    # But we've already disabled startup DB init in app.py for pytest
    client = TestClient(app)

    try:
        yield client
    finally:
        # Clean up dependency overrides
        app.dependency_overrides.clear()


@pytest.fixture
def sample_system_data():
    """Sample system data for testing."""
    return {
        "hostname": "test-system-1",
        "platform": "linux",
        "connectivity_status": "online",
    }


@pytest.fixture
def sample_snapshot_data():
    """Sample snapshot data for testing."""
    from datetime import datetime, timezone

    return {
        "name": "backup-20240115-120000",
        "pool": "tank",
        "dataset": "tank/data",
        "timestamp": datetime.now(timezone.utc),
        "size": 1024 * 1024,  # 1MB
    }


@pytest.fixture
def sample_sync_group_data():
    """Sample sync group data for testing."""
    return {
        "name": "test-sync-group",
        "description": "Test sync group for unit tests",
    }


@pytest.fixture
def temp_config_file():
    """Create a temporary config file for testing."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        config_content = """
app_name: "ZFS Sync Test"
app_version: "0.1.0-test"
debug: true
database_url: "sqlite:///:memory:"
api_prefix: "/api/v1"
"""
        f.write(config_content)
        temp_path = f.name

    yield temp_path

    # Cleanup
    if os.path.exists(temp_path):
        os.unlink(temp_path)
