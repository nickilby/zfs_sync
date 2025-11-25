"""Pytest configuration and shared fixtures."""

import os
import tempfile
from typing import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from zfs_sync.api.app import app
from zfs_sync.database.base import Base, get_db

# Import models to ensure they register with Base.metadata
import zfs_sync.database.models  # noqa: F401

# Use in-memory SQLite for tests
TEST_DATABASE_URL = "sqlite:///:memory:"


@pytest.fixture(scope="function")
def test_db() -> Generator[Session, None, None]:
    """Create a test database session with in-memory SQLite."""
    # Create a new engine for testing
    engine = create_engine(
        TEST_DATABASE_URL,
        connect_args={"check_same_thread": False},
        echo=False,
    )
    
    # Create all tables (models must be imported first for this to work)
    Base.metadata.create_all(bind=engine)
    
    # Create a session
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    session = TestingSessionLocal()
    
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


@pytest.fixture(scope="function")
def test_client(test_db: Session) -> Generator[TestClient, None, None]:
    """Create a test client with overridden database dependency."""
    # Override the get_db dependency
    def override_get_db():
        try:
            yield test_db
        finally:
            pass  # Don't close the session here, let test_db fixture handle it
    
    app.dependency_overrides[get_db] = override_get_db
    
    client = TestClient(app)
    try:
        yield client
    finally:
        # Clean up
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

