# ZFS Sync Architecture

## Overview

ZFS Sync is a witness service that coordinates ZFS snapshot synchronization across multiple systems. It follows a centralized witness pattern where the service maintains state and coordinates operations without directly managing ZFS pools.

## System Architecture

### High-Level Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    ZFS Sync Witness Service                  │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐     │
│  │   FastAPI    │  │   Services   │  │  Database   │     │
│  │   REST API   │  │   Layer      │  │  (SQLite/   │     │
│  │              │  │              │  │  PostgreSQL)│     │
│  └──────────────┘  └──────────────┘  └──────────────┘     │
└─────────────────────────────────────────────────────────────┘
         │                    │                    │
         │                    │                    │
    ┌────▼────┐         ┌────▼────┐         ┌────▼────┐
    │ System  │         │ System  │         │ System  │
    │   A     │         │   B     │         │   C     │
    │ (ZFS)   │         │ (ZFS)   │         │ (ZFS)   │
    └─────────┘         └─────────┘         └─────────┘
```

### Core Principles

1. **Witness Pattern**: The service observes and coordinates but does not execute ZFS commands directly
1. **Stateless API**: Systems report their state and receive instructions
1. **Repository Pattern**: Data access is abstracted through repository classes
1. **Service Layer**: Business logic is separated from API and data layers
1. **Configuration-Driven**: Flexible configuration via files and environment variables

## Component Design

### Application Layers

#### 1. API Layer (`zfs_sync/api/`)

**Purpose**: HTTP interface for client systems

**Components**:

- **FastAPI Application** (`app.py`): Main application setup, middleware, routing
- **Routes** (`routes/`): RESTful API endpoints
  - `health.py`: Health check endpoints
  - `systems.py`: System registration and management
  - `snapshots.py`: Snapshot reporting and querying
  - `sync_groups.py`: Sync group management
  - `sync.py`: Synchronization coordination endpoints
  - `conflicts.py`: Conflict detection and resolution
- **Schemas** (`schemas/`): Pydantic models for request/response validation
- **Middleware** (`middleware/auth.py`): API key authentication

**Key Features**:

- OpenAPI/Swagger documentation (auto-generated)
- CORS support
- Request validation via Pydantic
- API key authentication

#### 2. Service Layer (`zfs_sync/services/`)

**Purpose**: Business logic and coordination

**Services**:

- **SyncCoordinationService**: Detects mismatches and generates sync instructions
- **SnapshotComparisonService**: Compares snapshots across systems
- **ConflictResolutionService**: Detects and resolves conflicts
- **SnapshotHistoryService**: Tracks snapshot history and statistics
- **SystemHealthService**: Monitors system health and connectivity
- **AuthService**: API key generation and validation
- **SSHCommandGenerator**: Generates SSH commands for sync operations

**Design Patterns**:

- Service classes receive database session via dependency injection
- Services use repositories for data access
- Business logic is isolated from API and data layers

#### 3. Data Layer (`zfs_sync/database/`)

**Purpose**: Data persistence and access

**Components**:

- **Models** (`models.py`): SQLAlchemy ORM models
  - `SystemModel`: ZFS systems
  - `SnapshotModel`: ZFS snapshots
  - `SyncGroupModel`: Groups of systems to synchronize
  - `SyncStateModel`: Synchronization state tracking
  - `SyncGroupSystemModel`: Many-to-many association
- **Repositories** (`repositories/`): Data access abstraction
  - `SystemRepository`
  - `SnapshotRepository`
  - `SyncGroupRepository`
  - `SyncStateRepository`
  - `BaseRepository`: Common CRUD operations
- **Engine** (`engine.py`): Database connection management
- **Base** (`base.py`): Base model with common fields (id, created_at, updated_at)

**Database Support**:

- SQLite (default, for development)
- PostgreSQL (production)

#### 4. Configuration Layer (`zfs_sync/config/`)

**Purpose**: Application configuration management

**Features**:

- Environment variable support
- YAML/TOML configuration file support
- Platform-specific defaults (Linux, Windows, macOS)
- Configuration validation via Pydantic

#### 5. Domain Models (`zfs_sync/models/`)

**Purpose**: Core business domain models

**Models**:

- `System`: ZFS system representation
- `Snapshot`: ZFS snapshot representation
- `SyncGroup`: Group of systems to synchronize
- `SyncState`: Synchronization state with status enum

## Data Flow

### System Registration Flow

```
1. System → POST /api/v1/systems/register
2. API → AuthService.generate_api_key()
3. API → SystemRepository.create()
4. Database → Store system with API key
5. API → Return system details and API key
```

### Snapshot Reporting Flow

```
1. System → POST /api/v1/snapshots (with API key)
2. Middleware → Validate API key
3. API → SnapshotRepository.create_or_update()
4. Database → Store/update snapshot records
5. API → Return confirmation
```

### Sync Coordination Flow

```
1. System → GET /api/v1/sync/instructions/{system_id}
2. API → SyncCoordinationService.get_sync_instructions()
3. Service → Group datasets by dataset name (pool-agnostic)
4. Service → Compare snapshots across systems (normalized snapshot names)
5. Service → Detect mismatches (preserving pool information)
6. Service → Find incremental base snapshots (using correct pools)
7. Service → Generate dataset-grouped sync instructions
8. Service → Update sync states to 'syncing'
9. API → Return dataset-grouped instructions with:
   - Source pool and target pool
   - Starting snapshot (incremental base)
   - Ending snapshot (latest to sync)
   - SSH hostnames for source and target
10. System → Execute sync commands using provided information
```

### Conflict Detection Flow

```
1. System → GET /api/v1/conflicts/{sync_group_id}
2. API → ConflictResolutionService.detect_conflicts()
3. Service → Compare snapshots across systems
4. Service → Identify conflict types (diverged, orphaned, etc.)
5. Service → Apply resolution strategy
6. API → Return conflicts and resolution actions
```

## Database Schema

### Entity Relationship Diagram

```
┌─────────────┐         ┌──────────────┐         ┌─────────────┐
│   System    │────────<│   Snapshot   │         │ SyncGroup   │
│             │ 1:N     │              │         │             │
│ - id        │         │ - id         │         │ - id        │
│ - hostname  │         │ - name       │         │ - name      │
│ - platform  │         │ - pool       │         │ - enabled   │
│ - api_key   │         │ - dataset    │         └─────────────┘
│ - ssh_*     │         │ - timestamp  │                │
└─────────────┘         │ - system_id  │                │ N
                        └──────────────┘                │
                                │                       │
                                │ N                     │
                                │                       │
                        ┌───────▼───────────────────────▼──────┐
                        │         SyncState                     │
                        │                                       │
                        │ - sync_group_id                      │
                        │ - snapshot_id                         │
                        │ - system_id                           │
                        │ - status (in_sync/out_of_sync/etc)   │
                        │ - last_sync                           │
                        └───────────────────────────────────────┘
```

### Key Tables

**systems**

- Stores registered ZFS systems
- Includes SSH connection details for sync operations
- Tracks connectivity status and last seen timestamp

**snapshots**

- Stores snapshot metadata (name, pool, dataset, timestamp, size)
- Linked to systems via foreign key
- Indexed for efficient querying

**sync_groups**

- Groups systems that should maintain synchronized snapshots
- Configurable sync intervals
- Enable/disable flag

**sync_group_systems**

- Many-to-many association between sync groups and systems
- Allows systems to be in multiple sync groups

**sync_states**

- Tracks synchronization state for each snapshot in each sync group
- Status: in_sync, out_of_sync, syncing, error
- Tracks last sync and last check timestamps

## API Design

### RESTful Endpoints

**Base URL**: `/api/v1`

#### Health

- `GET /health` - Health check
- `GET /health/ready` - Readiness check
- `GET /health/live` - Liveness check

#### Systems

- `POST /systems/register` - Register a new system
- `GET /systems` - List all systems
- `GET /systems/{id}` - Get system details
- `PUT /systems/{id}` - Update system
- `DELETE /systems/{id}` - Delete system
- `POST /systems/{id}/heartbeat` - Update last seen timestamp

#### Snapshots

- `POST /snapshots` - Report single snapshot
- `POST /snapshots/batch` - Report multiple snapshots
- `GET /snapshots` - Query snapshots
- `GET /snapshots/{id}` - Get snapshot details
- `GET /snapshots/history` - Get snapshot history
- `GET /snapshots/statistics` - Get snapshot statistics

#### Sync Groups

- `POST /sync-groups` - Create sync group
- `GET /sync-groups` - List sync groups
- `GET /sync-groups/{id}` - Get sync group details
- `PUT /sync-groups/{id}` - Update sync group
- `DELETE /sync-groups/{id}` - Delete sync group
- `POST /sync-groups/{id}/systems` - Add system to group
- `DELETE /sync-groups/{id}/systems/{system_id}` - Remove system from group

#### Sync

- `GET /sync/instructions/{system_id}` - Get dataset-grouped sync instructions for a system
- `GET /sync/states` - List sync states
- `GET /sync/states/{id}` - Get sync state details
- `POST /sync/{sync_group_id}/check` - Trigger sync check

#### Conflicts

- `GET /conflicts/{sync_group_id}` - Get conflicts for sync group
- `POST /conflicts/{id}/resolve` - Resolve a conflict

### Authentication

- API key authentication via `X-API-Key` header
- API keys are generated during system registration
- Middleware validates API keys on protected endpoints

### Response Formats

- JSON responses
- Pydantic models ensure consistent structure
- Error responses follow standard format:

  ```json
  {
    "detail": "Error message",
    "status_code": 400
  }
  ```

## Deployment Architecture

### Docker Container Structure

```
Container: zfs-sync
├── /app              → Application code
├── /config           → Configuration files (read-only mount)
├── /logs             → Application logs (writable mount)
└── /data             → Database files (writable mount)
    └── zfs_sync.db   → SQLite database (or PostgreSQL connection)
```

### Multi-Stage Build

1. **Build Stage**: Install dependencies and compile
1. **Runtime Stage**: Minimal image with only runtime dependencies

### Security Features

- Non-root user (UID 1001)
- Health checks for container monitoring
- Resource limits (CPU, memory)
- Log rotation
- Read-only config mount

### Volume Mounts

- **Config**: `./config:/config:ro` (read-only)
- **Logs**: `./logs:/logs` (writable)
- **Data**: `/var/lib/zfs-sync:/data` (writable, persistent)

### Production Deployment

- Optional PostgreSQL database
- Stricter resource limits
- Enhanced logging configuration
- Health check dependencies

## Security Architecture

### Authentication & Authorization

- **API Keys**: Generated per system, stored securely
- **Key Length**: Configurable (default: 32 characters)
- **Validation**: Middleware validates keys on protected endpoints

### Data Security

- **Database**: SQLite (development) or PostgreSQL (production)
- **Connection Strings**: Configurable via environment variables
- **Secrets**: Never stored in code, use environment variables

### Network Security

- **CORS**: Configurable (currently permissive for development)
- **TLS/SSL**: Recommended for production (reverse proxy)
- **Firewall**: Restrict access to port 8000

### Container Security

- Non-root user execution
- Minimal base image
- Regular security updates
- Vulnerability scanning

## Synchronization Logic

### Dataset Comparison Strategy

The system uses **pool-agnostic dataset comparison**, meaning datasets are compared by dataset name only, regardless of pool differences. This allows systems with different pool names (e.g., `hqs10p1` vs `hqs7p1`) to synchronize the same logical dataset (e.g., `L1S4DAT1`).

**Key Points:**

- Datasets are grouped by dataset name across all systems in a sync group
- Each system's pool name is preserved and used when generating sync commands
- Snapshot names are normalized (pool/dataset prefix removed) for comparison
- Sync instructions include both source pool and target pool information

**Example:**

- System A: `hqs10p1/L1S4DAT1@2025-11-26-000000`
- System B: `hqs7p1/L1S4DAT1@2025-11-04-000000`
- The system recognizes these as the same logical dataset and detects that System B is missing snapshots from `2025-11-04-120000` through `2025-11-26-000000`

### Mismatch Detection

1. **Collect Snapshots**: Get all snapshots for systems in sync group
1. **Group by Dataset Name**: Organize snapshots by dataset name (ignoring pool differences)
1. **Map Pool Information**: Track which pool each system uses for each dataset
1. **Compare**: Find common snapshots and missing snapshots (using normalized snapshot names)
1. **Generate Actions**: Create sync actions with correct source and target pool information

### Sync Actions

- **CREATE**: Snapshot exists on source but not target
- **DELETE**: Snapshot exists on target but not source (optional)
- **SYNC**: Snapshot needs to be synchronized (incremental send)

### Conflict Types

- **DIVERGED**: Snapshots with same name but different timestamps
- **ORPHANED**: Snapshot exists but no common ancestor
- **MISSING**: Snapshot missing on one or more systems

### Resolution Strategies

- **use_newest**: Use the newest snapshot
- **use_largest**: Use the largest snapshot
- **use_majority**: Use snapshot present on majority of systems
- **manual**: Require manual intervention
- **ignore**: Ignore the conflict

## Logging & Monitoring

### Logging

- Structured logging with rotation
- Configurable log levels (DEBUG, INFO, WARNING, ERROR, CRITICAL)
- Log files stored in `/logs` directory
- JSON logging format for production

### Health Monitoring

- Health check endpoints
- System heartbeat mechanism
- Connectivity status tracking
- Last seen timestamp

### Observability (Future)

- Prometheus metrics (planned)
- System status dashboard (planned)
- Alerting system (planned)

## Configuration Management

### Configuration Sources (Priority Order)

1. **Environment Variables** (highest priority)

   - Format: `ZFS_SYNC_<SETTING_NAME>`
   - Example: `ZFS_SYNC_DATABASE_URL`

1. **Configuration File**

   - YAML or TOML format
   - Locations checked in order:
     - `zfs_sync.yaml` (current directory)
     - `config/zfs_sync.yaml` (config directory)

1. **Default Values** (lowest priority)

   - Platform-specific defaults
   - Sensible defaults for all settings

### Key Configuration Options

- Database URL (SQLite or PostgreSQL)
- Server host and port
- Log level
- API prefix
- Sync intervals
- Heartbeat timeout
- Secret key (for JWT/session management)

## Technology Stack

### Core Technologies

- **Python 3.9+**: Programming language
- **FastAPI**: Web framework
- **SQLAlchemy**: ORM and database abstraction
- **Pydantic**: Data validation and settings
- **Uvicorn**: ASGI server

### Database

- **SQLite**: Default for development
- **PostgreSQL**: Production option
- **Alembic**: Database migrations (setup, not yet used)

### Development Tools

- **pytest**: Testing framework
- **black**: Code formatting
- **ruff**: Linting
- **mypy**: Type checking

### Deployment

- **Docker**: Containerization
- **Docker Compose**: Orchestration
- **Multi-stage builds**: Optimized images

## Design Patterns

### Repository Pattern

Data access is abstracted through repository classes:

- `BaseRepository`: Common CRUD operations
- Specific repositories extend base for domain-specific queries
- Services use repositories, never access models directly

### Service Layer Pattern

Business logic is separated into service classes:

- Services receive database session via dependency injection
- Services orchestrate multiple repositories
- Services contain business rules and coordination logic

### Dependency Injection

- FastAPI's dependency injection for database sessions
- Services receive dependencies via constructor
- Enables easy testing with mock dependencies

### Witness Pattern

The application acts as a witness:

- Observes state from multiple systems
- Coordinates synchronization
- Does not execute ZFS commands directly
- Systems execute commands based on instructions

## Future Enhancements

### Planned Features

- Event-driven architecture with webhooks
- Prometheus metrics collection
- Web-based dashboard
- Kubernetes deployment examples
- Advanced monitoring and alerting
- Database migration system (Alembic)
- TLS/SSL support
- Rate limiting
- API key rotation

### Scalability Considerations

- Database connection pooling
- Async processing for large sync operations
- Caching layer for frequently accessed data
- Horizontal scaling with load balancer
- Read replicas for database (PostgreSQL)

## References

- [README.md](README.md) - Project overview and getting started
- [HOW_TO_USE.md](HOW_TO_USE.md) - User guide
- [QUICK_START.md](QUICK_START.md) - Quick setup guide
- API Documentation: Available at `/docs` when running the service
