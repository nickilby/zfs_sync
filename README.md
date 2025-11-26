# zfs_sync

A witness service to keep ZFS snapshots in sync across different platforms and systems.

## Overview

`zfs_sync` is designed to coordinate and synchronize ZFS snapshots across multiple systems, ensuring data consistency and enabling reliable backup and replication workflows. The application acts as a centralized witness that tracks snapshot states and coordinates synchronization operations between different ZFS pools and platforms.

## Purpose

The primary goal of this application is to:

- **Coordinate Snapshot Synchronization**: Maintain consistency of ZFS snapshots across multiple systems, whether they're on the same network or distributed across different locations
- **Cross-Platform Support**: Work seamlessly across different operating systems that support ZFS (Linux, FreeBSD, etc.)
- **Witness Pattern Implementation**: Act as a centralized witness service that tracks snapshot states and coordinates synchronization without directly managing the ZFS pools
- **Reliable Backup Workflows**: Enable reliable backup and disaster recovery scenarios by ensuring snapshots are synchronized before critical operations

## Planned Features

### Core Functionality

- **Snapshot State Tracking**: Monitor and track the state of ZFS snapshots across multiple systems
- **Synchronization Coordination**: Coordinate when snapshots should be created and synchronized
- **Conflict Resolution**: Handle conflicts when snapshots diverge between systems
- **Health Monitoring**: Monitor the health and connectivity of ZFS systems

### Technical Capabilities

- **RESTful API**: Provide an API for systems to report snapshot states and request synchronization
- **Event-Driven Architecture**: React to snapshot events and coordinate responses
- **Configuration Management**: Support flexible configuration for different deployment scenarios
- **Logging and Auditing**: Comprehensive logging of synchronization operations

## Architecture

The application will follow a witness pattern where:

1. **Witness Service**: Central service that maintains state and coordinates operations
2. **ZFS Clients**: Systems with ZFS pools that report their snapshot states to the witness
3. **Synchronization Protocol**: Defined protocol for how clients communicate snapshot states and receive synchronization instructions

## Use Cases

- **Multi-Site Backup**: Keep snapshots synchronized across geographically distributed systems
- **Disaster Recovery**: Ensure critical snapshots exist on multiple systems before disaster scenarios
- **Data Replication**: Coordinate snapshot creation before replication operations
- **Backup Verification**: Verify that backup snapshots are consistent across systems

## Implementation Plan

Based on the architecture and requirements outlined above, here's the step-by-step plan to build `zfs_sync`:

### Phase 1: Foundation & Project Setup

1. **Choose Technology Stack**

   - Select programming language (Python, Go, or Rust recommended for cross-platform support)
   - Set up project structure and dependency management
   - Initialize version control and basic project scaffolding

2. **Define Core Data Models**

   - `System`: Represents a ZFS system with metadata (ID, hostname, platform, connectivity status)
   - `Snapshot`: Represents a ZFS snapshot with metadata (name, pool, dataset, timestamp, size)
   - `SyncGroup`: Groups systems that should maintain synchronized snapshots
   - `SyncState`: Tracks the synchronization state between systems

3. **Set Up Configuration System**

   - Configuration file format (YAML/JSON/TOML)
   - Environment variable support
   - Default configuration values
   - Configuration validation

### Phase 2: Core Infrastructure

1. **Implement State Storage**

   - Choose storage backend (SQLite for simplicity, PostgreSQL for production)
   - Design database schema for systems, snapshots, and sync states
   - Implement data access layer (repository pattern)

2. **Build RESTful API Foundation**

   - Set up web framework (Flask/FastAPI for Python, Gin/Echo for Go, Actix for Rust)
   - Define API routes structure:
     - `/api/v1/systems` - System registration and management
     - `/api/v1/snapshots` - Snapshot state reporting
     - `/api/v1/sync` - Synchronization coordination
     - `/api/v1/health` - Health checks
   - Implement request/response models
   - Add basic error handling and validation

3. **Implement Logging System**

   - Structured logging setup
   - Log levels and rotation
   - Audit trail for synchronization operations

### Phase 3: Core Functionality

1. **System Registration & Management**

   - Endpoint for systems to register themselves
   - System authentication/authorization (API keys or tokens)
   - System health monitoring and heartbeat mechanism
   - System metadata management

2. **Snapshot State Tracking**

   - Endpoint for systems to report their snapshot states
   - Snapshot state comparison logic
   - Snapshot metadata storage and retrieval
   - Snapshot history tracking

3. **Synchronization Coordination**

   - Algorithm to detect snapshot mismatches
   - Coordination logic to determine sync actions
   - Endpoint for systems to query sync instructions
   - Sync status tracking and reporting
   - Sync actions include snapshot_id for efficient state updates

### Phase 4: Advanced Features

1. **Conflict Resolution**

   - Detect conflicts when snapshots diverge
   - Implement conflict resolution strategies
   - Manual intervention support for complex conflicts

2. **Event-Driven Architecture**

   - Event system for snapshot events
   - Webhook support for external integrations
   - Event queue for async processing

3. **Monitoring & Observability**

   - Metrics collection (Prometheus compatible)
   - Health check endpoints
   - System status dashboard (basic CLI or web)

### Phase 5: Testing & Documentation

1. **Testing**

   - Unit tests for core logic
   - Integration tests for API endpoints
   - End-to-end tests with mock ZFS systems
   - Performance testing

2. **Documentation**

   - API documentation (OpenAPI/Swagger)
   - Client library examples
   - Deployment guides
   - Configuration reference

### Phase 6: Production Readiness

1. **Security Hardening**

   - Authentication and authorization
   - TLS/SSL support
   - Input validation and sanitization
   - Rate limiting

2. **Deployment & Operations**

   - Containerization (Docker)
   - Deployment examples (Docker Compose, Kubernetes)
   - Backup and recovery procedures
   - Monitoring and alerting setup

## Getting Started

### For End Users

**New to ZFS Sync?** Start with the **[How to Use Guide](HOW_TO_USE.md)** - a beginner-friendly walkthrough that explains how to set up and use the system step-by-step.

### For Developers

To begin implementation, start with **Phase 1** and work through each phase sequentially. Each phase builds upon the previous one, ensuring a solid foundation before adding complexity.

### Development Workflow

The application can be developed and tested in two ways:

#### Option 1: Local Development (Recommended for Development)

For active development, testing, and debugging:

```bash
# Install dependencies
pip install -r requirements-dev.txt

# Run tests
pytest

# Run the application locally
python -m zfs_sync
```

**Advantages:**

- Faster iteration cycle
- Easier debugging with IDE integration
- Direct access to logs and files
- No need to rebuild Docker images for every change

#### Option 2: Docker Development (Recommended for Testing Production-like Environment)

For testing the containerized deployment:

```bash
# Build the Docker image
make docker-build
# or: docker-compose build

# Start the container
make docker-up
# or: docker-compose up -d

# View logs
make docker-logs
# or: docker-compose logs -f

# Stop the container
make docker-down
# or: docker-compose down
```

**Advantages:**

- Tests the exact production environment
- Isolated dependencies
- Consistent across different machines
- Easy to test with different configurations

**Recommended Approach:**

- Use **local development** for day-to-day coding and testing
- Use **Docker** to verify the containerized deployment works correctly
- Both approaches are supported and can be used interchangeably

### Production Deployment

The application is production-ready with Docker and includes security best practices, health checks, and resource management.

#### Quick Start (Development/Testing with SQLite)

For development or small deployments using SQLite:

```bash
# Build and start the container
docker-compose up -d

# View logs
docker-compose logs -f

# Check health
curl http://localhost:8000/api/v1/health

# Stop the container
docker-compose down
```

#### Production Deployment (with PostgreSQL)

For production deployments, use the production override file which includes PostgreSQL:

```bash
# Set PostgreSQL password (required)
export POSTGRES_PASSWORD=your-secure-password-here

# Set secret key for JWT/session management (recommended)
export ZFS_SYNC_SECRET_KEY=your-secret-key-here

# Build and start with production configuration
docker-compose -f docker-compose.yml -f docker-compose.prod.yml up -d

# View logs
docker-compose -f docker-compose.yml -f docker-compose.prod.yml logs -f

# Stop
docker-compose -f docker-compose.yml -f docker-compose.prod.yml down
```

#### Production Features

The production Docker setup includes:

- **Multi-stage build**: Optimized image size with separate build and runtime stages
- **Non-root user**: Application runs as dedicated `zfssync` user (UID 1000) for security
- **Health checks**: Built-in health monitoring with automatic restart on failure
- **Resource limits**: CPU and memory limits to prevent resource exhaustion
- **Logging**: Structured JSON logging with rotation (50MB files, 5 files retained)
- **PostgreSQL support**: Optional PostgreSQL database for production workloads
- **Volume persistence**: Data, logs, and configuration persisted via Docker volumes
- **Restart policies**: Automatic restart on failure (`unless-stopped`)

#### Configuration

Configuration can be provided via:

1. **Environment variables** (recommended for production):
   ```bash
   export ZFS_SYNC_DATABASE_URL=postgresql://user:pass@host:5432/db
   export ZFS_SYNC_LOG_LEVEL=INFO
   export ZFS_SYNC_SECRET_KEY=your-secret-key
   ```

2. **Config file** (mounted as volume):
   - Place `zfs_sync.yaml` in the `./config` directory
   - It will be automatically loaded by the application

3. **Docker Compose environment variables**:
   - Edit `docker-compose.yml` or `docker-compose.prod.yml`
   - Set environment variables in the `environment` section

#### Data Persistence

Important data is persisted via Docker volumes:

- **Database**: `./data` directory (SQLite) or PostgreSQL volume (production)
- **Logs**: `./logs` directory
- **Configuration**: `./config` directory (read-only mount)

**Backup Recommendations:**

- Regularly backup the `./data` directory for SQLite deployments
- Use PostgreSQL backup tools (`pg_dump`) for production deployments
- Consider automated backup solutions for production environments

#### Security Considerations

1. **Secrets Management**: Never commit secrets to version control. Use:
   - Environment variables
   - Docker secrets (Docker Swarm)
   - External secret management (HashiCorp Vault, AWS Secrets Manager, etc.)

2. **Network Security**: 
   - Use reverse proxy (nginx, Traefik) with TLS/SSL termination
   - Restrict container network access
   - Use firewall rules to limit access to port 8000

3. **Database Security**:
   - Use strong PostgreSQL passwords
   - Enable SSL/TLS for database connections
   - Restrict database network access

4. **Container Security**:
   - Regularly update base images
   - Scan images for vulnerabilities
   - Run as non-root user (already configured)

#### Monitoring

The container includes health checks that can be monitored:

```bash
# Check container health status
docker ps

# View health check logs
docker inspect zfs-sync | grep -A 10 Health

# Manual health check
curl http://localhost:8000/api/v1/health
```

#### Troubleshooting

**Container won't start:**
```bash
# Check logs
docker-compose logs zfs-sync

# Check container status
docker ps -a

# Verify volumes are mounted correctly
docker inspect zfs-sync | grep -A 20 Mounts
```

**Database connection issues:**
- Verify `ZFS_SYNC_DATABASE_URL` is correct
- For PostgreSQL, ensure the database service is healthy: `docker-compose ps postgres`
- Check database logs: `docker-compose logs postgres`

**Permission issues:**
- The container runs as UID 1000. Ensure mounted volumes have correct permissions
- For data directory: `chown -R 1000:1000 ./data ./logs`

### Recommended First Steps

1. Choose a programming language based on team expertise and requirements ✓ (Python selected)
2. Set up the project repository structure ✓
3. Implement basic configuration management ✓
4. Create the core data models ✓
5. Set up a simple REST API with one endpoint to verify the stack works (Phase 2)

## Development Status

**Phase 1: Foundation & Project Setup** - ✅ **COMPLETE**

- ✅ Python project structure and dependency management
- ✅ Core data models (System, Snapshot, SyncGroup, SyncState)
- ✅ Configuration system with YAML/TOML and environment variable support
- ✅ Docker support for containerized deployment

**Phase 2: Core Infrastructure** - ✅ **COMPLETE**

- ✅ State storage with SQLAlchemy (SQLite/PostgreSQL support)
- ✅ Database models and repository pattern
- ✅ RESTful API foundation with FastAPI
- ✅ Structured logging system with rotation

**Phase 3: Core Functionality** - ✅ **COMPLETE**

- ✅ System Registration & Management (API keys, heartbeat, health monitoring)
- ✅ Snapshot State Tracking (comparison, history, statistics)
- ✅ Synchronization Coordination (mismatch detection, sync actions, instructions)

**Overall Progress: ~65% Complete**

See [STATUS.md](STATUS.md) for detailed status of all phases and remaining work.

## Future Considerations

- Support for different ZFS implementations (OpenZFS, ZFS on Linux, etc.)
- Integration with existing backup and monitoring tools
- Web-based dashboard for monitoring synchronization status
- Support for encrypted snapshots and secure communication
