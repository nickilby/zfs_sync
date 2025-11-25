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

- `test_db`: In-memory SQLite database session (function-scoped)
- `test_client`: FastAPI TestClient with database override
- `sample_system_data`: Sample data for creating test systems
- `sample_snapshot_data`: Sample data for creating test snapshots
- `sample_sync_group_data`: Sample data for creating test sync groups

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

## Notes

- All tests use an in-memory SQLite database for speed and isolation
- Each test function gets a fresh database session
- The test client automatically overrides the database dependency

