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

The application follows a witness pattern where:

1. **Witness Service**: Central service that maintains state and coordinates operations
2. **ZFS Clients**: Systems with ZFS pools that report their snapshot states to the witness
3. **Synchronization Protocol**: Defined protocol for how clients communicate snapshot states and receive synchronization instructions

For comprehensive architecture documentation, see [ARCHITECTURE.md](ARCHITECTURE.md).

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
# Create persistent data directory (required, one-time setup)
sudo mkdir -p /var/lib/zfs-sync
sudo chown -R 1001:1001 /var/lib/zfs-sync
sudo chmod 755 /var/lib/zfs-sync

# Build and start the container
docker-compose up -d

# View logs
docker-compose logs -f

# Check health
curl http://localhost:8000/api/v1/health

# Stop the container
docker-compose down
```

**Note:** The database is stored in `/var/lib/zfs-sync/` on the host system, ensuring it persists across container updates and app refreshes.

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
- **Non-root user**: Application runs as dedicated `zfssync` user (UID 1001) for security
- **Health checks**: Built-in health monitoring with automatic restart on failure
- **Resource limits**: CPU and memory limits to prevent resource exhaustion
- **Logging**: Structured JSON logging with rotation (50MB files, 5 files retained)
- **PostgreSQL support**: Optional PostgreSQL database for production workloads
- **Volume persistence**: Data, logs, and configuration persisted via Docker volumes
- **Restart policies**: Automatic restart on failure (`unless-stopped`)

#### Configuration

Configuration can be provided via (in order of precedence, highest first):

1. **Environment variables** (recommended for production, highest priority):

   ```bash
   export ZFS_SYNC_DATABASE_URL=postgresql://user:pass@host:5432/db
   # Or for custom SQLite location:
   export ZFS_SYNC_DATABASE_URL=sqlite:////custom/path/zfs_sync.db
   export ZFS_SYNC_LOG_LEVEL=INFO
   export ZFS_SYNC_SECRET_KEY=your-secret-key
   ```

2. **Config file** (mounted as volume):
   - Place `zfs_sync.yaml` in the `./config` directory
   - It will be automatically loaded by the application
   - Can override default database path: `database_url: "sqlite:////custom/path/zfs_sync.db"`

3. **Docker Compose environment variables**:
   - Edit `docker-compose.yml` or `docker-compose.prod.yml`
   - Set environment variables in the `environment` section

4. **Default values** (lowest priority):
   - Platform-specific defaults are used if nothing else is configured
   - Linux: `/var/lib/zfs-sync/zfs_sync.db`

#### Data Persistence

Important data is persisted via Docker volumes:

- **Database**: `/var/lib/zfs-sync/` directory on host (SQLite) or PostgreSQL volume (production)
  - Default location: `/var/lib/zfs-sync/zfs_sync.db` (persists outside app directory)
  - This ensures the database survives app updates and directory refreshes
  - Can be overridden via `ZFS_SYNC_DATABASE_URL` environment variable or config file
- **Logs**: `./logs` directory (relative to docker-compose.yml)
- **Configuration**: `./config` directory (read-only mount)

**Database Location Details:**

The application uses platform-specific default database locations:

- **Linux (Docker)**: `/var/lib/zfs-sync/zfs_sync.db` (mounted to `/data/zfs_sync.db` in container)
- **Windows**: `%APPDATA%/zfs-sync/zfs_sync.db`
- **macOS/Other Unix**: `~/.local/share/zfs-sync/zfs_sync.db`

**Permissions Setup (Required for Docker):**

The `/var/lib/zfs-sync` directory must exist and be writable by the container user (UID 1001):

```bash
# Create the directory
sudo mkdir -p /var/lib/zfs-sync

# Set ownership to UID 1001 (zfssync user in container)
sudo chown -R 1001:1001 /var/lib/zfs-sync

# Set appropriate permissions
sudo chmod 755 /var/lib/zfs-sync
```

**Ansible Deployment:**

For Ansible playbooks, include the following tasks to set up the persistent data directory:

```yaml
- name: Create zfs-sync data directory
  file:
    path: /var/lib/zfs-sync
    state: directory
    owner: "1001"
    group: "1001"
    mode: "0755"

- name: Ensure zfs-sync data directory persists
  lineinfile:
    path: /etc/fstab
    line: "# zfs-sync data directory - do not remove"
    create: yes
  when: ansible_os_family == "RedHat" or ansible_os_family == "Debian"
```

**Backup Recommendations:**

- Regularly backup the `/var/lib/zfs-sync/` directory for SQLite deployments
- Use PostgreSQL backup tools (`pg_dump`) for production deployments
- Consider automated backup solutions for production environments
- The database location is outside the application directory, so it won't be affected by app updates

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

**Database Schema Errors (500 Internal Server Error):**

If you see errors like `no such column: sync_groups.description` or `no such column: systems.ssh_hostname`, this indicates a database schema mismatch. This typically happens when the database was moved to a new location with an old schema.

**Solution (Recommended - Recreate Database):**

```bash
# 1. Fix permissions first
sudo chown -R 1001:1001 /var/lib/zfs-sync
sudo chmod 755 /var/lib/zfs-sync

# 2. Backup existing database (optional, if you want to keep a copy)
sudo cp /var/lib/zfs-sync/zfs_sync.db /var/lib/zfs-sync/zfs_sync.db.backup

# 3. Delete old database - app will recreate with correct schema on restart
sudo rm /var/lib/zfs-sync/zfs_sync.db

# 4. Restart container - it will automatically create a fresh database with correct schema
docker-compose restart zfs-sync
```

The application will automatically create a new database with the correct schema when it starts. All systems will need to re-register, and snapshots will need to be reported again.

**Alternative: Database Migrations (if you need to preserve data):**

If you need to preserve existing data, you can use Alembic migrations (see Database Migrations section below).

**Database Permissions Issues:**

If the database file is owned by a different user (e.g., `username:username` instead of UID 1001):

```bash
# Check current ownership
ls -lah /var/lib/zfs-sync/

# Fix ownership to match container user (UID 1001)
sudo chown -R 1001:1001 /var/lib/zfs-sync
sudo chmod 755 /var/lib/zfs-sync
```

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
- For SQLite, ensure `/var/lib/zfs-sync` directory exists and has correct permissions:

  ```bash
  # Check if directory exists
  ls -la /var/lib/zfs-sync
  
  # Fix permissions if needed
  sudo mkdir -p /var/lib/zfs-sync
  sudo chown -R 1001:1001 /var/lib/zfs-sync
  sudo chmod 755 /var/lib/zfs-sync
  ```

**Database Migrations (Optional - for preserving existing data):**

If you need to preserve existing data instead of recreating the database, you can use Alembic migrations. Note: This requires proper Alembic configuration setup.

Available migrations:

- `001_add_ssh_fields_to_systems.py` - Adds SSH connection fields to systems table
- `002_add_description_to_sync_groups.py` - Adds description field to sync_groups table

For most deployments, recreating the database (as shown above) is simpler and recommended.

**Permission issues:**

- The container runs as UID 1001. Ensure mounted volumes have correct permissions
- For data directory: `sudo chown -R 1001:1001 /var/lib/zfs-sync`
- Check container user: `docker exec zfs-sync id`

### Recommended First Steps

1. Choose a programming language based on team expertise and requirements ✓ (Python selected)
2. Set up the project repository structure ✓
3. Implement basic configuration management ✓
4. Create the core data models ✓
5. Set up a simple REST API with one endpoint to verify the stack works (Phase 2)

## Development Status

The core functionality of ZFS Sync is **complete and production-ready**. The application provides:

- ✅ System Registration & Management (API keys, heartbeat, health monitoring)
- ✅ Snapshot State Tracking (comparison, history, statistics)
- ✅ Synchronization Coordination (mismatch detection, sync actions, instructions)
- ✅ Conflict Detection & Resolution
- ✅ RESTful API with OpenAPI documentation
- ✅ Docker containerization with production-ready configuration
- ✅ Database support (SQLite/PostgreSQL)
- ✅ Comprehensive logging and health monitoring

For detailed architecture information, see [ARCHITECTURE.md](ARCHITECTURE.md).

## Future Considerations

- Support for different ZFS implementations (OpenZFS, ZFS on Linux, etc.)
- Integration with existing backup and monitoring tools
- Web-based dashboard for monitoring synchronization status
- Support for encrypted snapshots and secure communication
