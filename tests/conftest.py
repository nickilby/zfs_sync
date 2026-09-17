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

# Each test gets its own database file.
#
# A single module-level file was shared by the whole session, and the teardown
# deleted it -- so tests were order-dependent and could not run in parallel:
# under pytest-xdist one worker would remove the file another was still using.
# File-based rather than in-memory because in-memory SQLite gives each
# connection its own database.


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
        "sync_runs",
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
        "sync_runs",
    }

    missing_tables = expected_tables - existing_tables
    if missing_tables:
        raise RuntimeError(
            f"Missing database tables: {missing_tables}. "
            f"Existing tables: {existing_tables}. "
            f"This indicates a problem with database initialization."
        )


@pytest.fixture(scope="function")
def test_database_url(tmp_path) -> str:
    """A database URL unique to this test."""
    return f"sqlite:///{tmp_path / 'test.db'}"


@pytest.fixture(scope="function")
def test_db(test_database_url: str) -> Generator[Session, None, None]:
    """A session against this test's own database."""
    engine = create_engine(
        test_database_url,
        connect_args={"check_same_thread": False},
        echo=False,
    )

    # Models are imported at module level, so the metadata is populated.
    Base.metadata.create_all(bind=engine)
    verify_tables_exist(engine)

    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    session = TestingSessionLocal()

    try:
        yield session
    finally:
        session.close()
        engine.dispose()
        # tmp_path is removed by pytest, so there is no file to clean up and
        # no shared file for another worker to pull out from under us.


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


@pytest.fixture
def registered_system(test_client):
    """A registered system: returns its id and the plaintext API key.

    The key is only ever returned at registration -- it is stored as a digest
    -- so tests that need to authenticate must capture it here.
    """
    response = test_client.post(
        "/api/v1/systems",
        json={
            "hostname": "fixture-system",
            "platform": "linux",
            "connectivity_status": "online",
            "ssh_hostname": "fixture-system-san",
        },
    )
    assert response.status_code == 201, response.text
    body = response.json()
    return body["id"], body["api_key"]


@pytest.fixture
def auth_client(test_client, registered_system):
    """A client that authenticates as `registered_system` by default.

    Most endpoints require a key now; only registration, the health probes and
    the dashboard page do not. Individual requests can still override or drop
    the header to exercise the rejection paths.
    """
    _system_id, api_key = registered_system
    test_client.headers.update({"X-API-Key": api_key})
    return test_client


def pytest_collection_modifyitems(config, items):
    """Apply the unit/integration markers by location.

    Both markers were declared in pyproject with --strict-markers and applied
    by no test, so `pytest -m unit` selected nothing and the CI benchmark job
    was permanently vacuous. Deriving them from the directory keeps them true
    without asking every test to remember a decorator.
    """
    for item in items:
        path = str(item.fspath).replace("\\", "/")
        if "/tests/unit/" in path:
            item.add_marker(pytest.mark.unit)
        elif "/tests/integration/" in path:
            item.add_marker(pytest.mark.integration)

        if "migration" in path:
            # These build and tear down whole schemas.
            item.add_marker(pytest.mark.slow)
        if "test_db" in getattr(item, "fixturenames", ()):
            item.add_marker(pytest.mark.database)
