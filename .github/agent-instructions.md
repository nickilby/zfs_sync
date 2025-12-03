# Agent Instructions for ZFS Sync Project

## Project Overview

ZFS Sync is a **witness service** that coordinates ZFS snapshot synchronization across multiple systems without directly managing ZFS pools. It acts as a centralized coordinator that tracks snapshot states, detects conflicts, and provides executable sync instructions.

### Core Functionality

- Track snapshot states across distributed ZFS systems
- Detect synchronization mismatches and conflicts
- Generate ready-to-execute SSH commands for ZFS send/receive
- Monitor system health and connectivity
- Resolve conflicts through multiple resolution strategies
- Coordinate cross-platform synchronization (Linux, FreeBSD, etc.)

## Architecture Overview

### Core Components

```text
zfs_sync/
├── api/          # FastAPI web service with OpenAPI docs
├── database/     # SQLAlchemy models and repositories
├── services/     # Business logic layer
├── models/       # Domain models (System, Snapshot, SyncGroup, SyncState)
└── config/       # Configuration management
```

### Key Patterns

- **Repository Pattern**: Clean data access abstraction in `database/repositories/`
- **Service Layer**: Business logic in `services/` (sync coordination, conflict resolution)
- **Dependency Injection**: FastAPI's built-in DI system
- **Witness Pattern**: Central coordination without direct ZFS management

### Domain Models

- **System**: ZFS systems with SSH connectivity details
- **Snapshot**: ZFS snapshot metadata (name, timestamp, size)
- **SyncGroup**: Groups of systems that should stay synchronized
- **SyncState**: Tracks synchronization status between systems

## Technology Stack

- **Python 3.9+** with comprehensive type hints
- **FastAPI** with auto-generated OpenAPI documentation
- **SQLAlchemy 2.0** with async support
- **Pydantic 2.0** for validation and settings
- **SQLite/PostgreSQL** database support
- **Docker** with multi-stage builds
- **pytest** with fixtures and markers

## Authentication Status

### Current Implementation

- **Infrastructure**: Complete API key system exists but selectively applied
- **Authenticated Endpoints**: Only API key management (`/systems/{id}/api-key/*`) and heartbeat endpoints
- **Public Endpoints**: All core functionality (systems, snapshots, sync operations) currently requires no authentication
- **Header Format**: `X-API-Key` when authentication is required

### For Agents

- Most endpoints are currently open for development ease
- Authentication infrastructure is ready for broader deployment
- When adding new endpoints, follow existing patterns in `api/middleware/auth.py`

## Development Standards

### Code Quality

- **Type Safety**: All functions must have type hints
- **Error Handling**: Use structured exceptions with proper HTTP status codes
- **Documentation**: FastAPI auto-generates docs, but complex business logic needs docstrings
- **Formatting**: Black formatting enforced in CI
- **Linting**: Ruff linting with mypy type checking

### API Design

- **RESTful**: Standard HTTP methods and status codes
- **Consistent Responses**: Use Pydantic schemas in `api/schemas/`
- **Validation**: Pydantic models for request/response validation
- **Error Format**: Consistent error responses with detail messages

### Database Patterns

- **Repository Pattern**: All database access through `database/repositories/`
- **Migrations**: Alembic configured (in `alembic/`) but migrations should be minimal
- **Sessions**: Use dependency injection for database sessions
- **Models**: SQLAlchemy models in `database/models.py`, domain models in `models/`

## Testing Requirements

### Test Structure

```text
tests/
├── unit/           # Service and repository layer tests
├── integration/    # API endpoint tests with real database
└── conftest.py     # Shared fixtures and test configuration
```

### Testing Standards

- **Unit Tests**: Focus on service layer business logic (`services/`)
- **Integration Tests**: API endpoints with database interactions
- **Fixtures**: Use provided database fixtures for consistent test data
- **Markers**: Use `@pytest.mark.unit`, `@pytest.mark.integration` markers
- **Coverage**: Maintain test coverage for new code

### Current Test Gaps (Opportunities)

- Missing tests for sync routes (`/sync/*`)
- Missing tests for conflict routes (`/conflicts/*`)
- Limited service layer coverage
- No authentication middleware edge case tests
- No performance/benchmark tests (infrastructure exists)

## ZFS Domain Knowledge

### ZFS Concepts

- **Snapshots**: Point-in-time dataset copies with names like `tank/data@backup-2024-12-02`
- **Pools and Datasets**: Hierarchical storage organization
- **Send/Receive**: Native ZFS replication mechanism
- **Incremental Sends**: Efficient delta transfers between snapshots

### Command Generation

- **SSH Piping**: `ssh 'zfs send ...' | ssh 'zfs receive ...'`
- **Force Receive**: Use `-F` flag to overwrite existing datasets
- **Incremental Syntax**: `zfs send -i @old-snap dataset@new-snap`
- **Security**: Commands are generated in `services/ssh_command_generator.py` with proper escaping

### Conflict Types

- **Divergent Snapshots**: Same name, different content/timestamps
- **Missing Base**: Broken incremental chains
- **Size Mismatches**: Potential data integrity issues
- **Timestamp Issues**: Same snapshot, different creation times

## Configuration Management

### Configuration Sources (Priority Order)

1. Environment variables with `ZFS_SYNC_` prefix
2. `config/zfs_sync.yaml` file
3. Default values in `config/settings.py`

### Key Configuration Areas

- **Database**: Connection strings and pool settings
- **SSH**: Connection timeouts and command settings
- **API**: Port, host, and authentication settings
- **Logging**: Levels and output formats

## Common Development Tasks

### Adding New API Endpoints

1. Create Pydantic schemas in `api/schemas/`
2. Add route handlers in appropriate `api/routes/` file
3. Add business logic to relevant service in `services/`
4. Write integration tests in `tests/integration/test_api/`

### Adding New Services

1. Create service class in `services/`
2. Follow dependency injection patterns
3. Add comprehensive unit tests in `tests/unit/test_services/`
4. Consider error handling and logging

### Database Changes

1. Modify models in `database/models.py`
2. Update repository methods in `database/repositories/`
3. Consider if migration is needed (prefer avoiding schema changes)
4. Update relevant domain models in `models/`

### Adding Authentication

- Use `get_api_key_auth` dependency from `api/middleware/auth.py`
- Follow patterns from existing authenticated endpoints
- Add tests for authentication scenarios

## Deployment Context

### Docker

- Multi-stage Dockerfile with production optimizations
- Health check endpoint at `/health`
- Environment variable configuration support
- Docker Compose for development and deployment

### Production Considerations

- Database connection pooling configured
- Structured logging with JSON output
- Health monitoring endpoints available
- SSH command security with proper escaping

## Important Notes

### What NOT to Do

- Don't bypass the repository pattern for database access
- Don't add direct ZFS command execution (this is a witness service)
- Don't modify SSH key management (agents don't need to know this)
- Don't break the witness pattern by adding direct pool management

### Performance Considerations

- Use async/await patterns consistently
- Database queries should be efficient (consider indexes)
- SSH command generation should be fast (no actual execution)
- Consider pagination for large result sets

### Security Notes

- SSH commands are generated, not executed by this service
- API keys are stored hashed in database
- Input validation through Pydantic is critical
- No sensitive data should be logged

## Current Project Status

**Completion**: ~72% (Production-ready core functionality)

- ✅ Core API and business logic
- ✅ Database layer with repositories
- ✅ Docker deployment ready
- ⚠️ Security (basic auth implemented, TLS/rate limiting pending)
- ⚠️ Testing (good coverage, but gaps exist)
- ⚠️ Monitoring (health checks exist, metrics pending)

This project represents a sophisticated ZFS synchronization coordination service with clean architecture, comprehensive API design, and deep domain knowledge integration suitable for enterprise backup and replication workflows.
