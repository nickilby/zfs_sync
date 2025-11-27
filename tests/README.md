# Test Suite

This directory contains the test suite for `zfs_sync`.

## Structure

```
tests/
├── conftest.py              # Shared pytest fixtures
├── unit/                    # Unit tests
│   ├── test_services/       # Service layer tests
│   └── test_repositories/   # Repository layer tests
└── integration/             # Integration tests
    └── test_api/            # API endpoint tests
```

## Running Tests

### Run all tests
```bash
pytest
```

### Run with coverage
```bash
pytest --cov=zfs_sync --cov-report=html
```

### Run only unit tests
```bash
pytest tests/unit/
```

### Run only integration tests
```bash
pytest tests/integration/
```

### Run specific test file
```bash
pytest tests/unit/test_services/test_conflict_resolution.py
```

### Run with verbose output
```bash
pytest -v
```

## Test Fixtures

The `conftest.py` file provides shared fixtures:

- `verify_database_setup`: Autouse fixture that verifies database models are registered (session-scoped)
- `test_db`: In-memory SQLite database session with automatic table creation and verification (function-scoped)
- `test_client`: FastAPI TestClient with database dependency override and table verification
- `sample_system_data`: Sample data for creating test systems
- `sample_snapshot_data`: Sample data for creating test snapshots
- `sample_sync_group_data`: Sample data for creating test sync groups

### Database Setup

The test suite uses a robust database initialization approach:

1. **Model Registration Verification**: An autouse fixture verifies all database models are properly registered with SQLAlchemy's metadata before any tests run.

2. **Table Creation**: Each test gets a fresh in-memory SQLite database with all tables automatically created via the `test_db` fixture.

3. **Table Verification**: Before each test runs, the fixtures verify that all expected tables exist in the database, providing clear error messages if something goes wrong.

4. **Isolation**: Each test function gets a completely fresh database, ensuring tests don't interfere with each other.

5. **Startup Event Handling**: The app's startup event is automatically disabled during tests to prevent interference with test database setup.

## Writing New Tests

### Unit Tests

Unit tests should test individual components in isolation:

```python
def test_my_service_method(test_db, sample_system_data):
    """Test description."""
    # Arrange
    repo = SystemRepository(test_db)
    system = repo.create(**sample_system_data)
    
    # Act
    result = my_service.do_something(system.id)
    
    # Assert
    assert result is not None
```

### Integration Tests

Integration tests should test API endpoints:

```python
def test_create_system_endpoint(test_client):
    """Test system creation endpoint."""
    response = test_client.post(
        "/api/v1/systems/register",
        json={"hostname": "test", "platform": "linux"},
    )
    assert response.status_code == 201
```

## Test Markers

The test suite uses pytest markers to categorize tests:

- `@pytest.mark.unit`: Unit tests (isolated component tests)
- `@pytest.mark.integration`: Integration tests (API endpoint tests)
- `@pytest.mark.slow`: Slow-running tests
- `@pytest.mark.benchmark`: Performance benchmark tests
- `@pytest.mark.database`: Tests that require database access

Example:
```python
@pytest.mark.integration
@pytest.mark.database
def test_create_system(test_client):
    """Test system creation."""
    ...
```

## Notes

- All tests use an in-memory SQLite database for speed and isolation
- Each test function gets a fresh database session with all tables pre-created
- The test client automatically overrides the database dependency
- Database tables are verified to exist before each test runs
- If database initialization fails, you'll get clear error messages indicating which tables are missing
- The app startup event is automatically disabled during tests to prevent database conflicts

