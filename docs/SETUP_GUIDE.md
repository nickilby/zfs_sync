# ZFS Sync Setup Guide

A comprehensive guide for technical users setting up ZFS Sync v2.0 for the first time.

## Table of Contents

1. [Prerequisites](#prerequisites)
2. [Installation Options](#installation-options)
3. [Initial Configuration](#initial-configuration)
4. [System Registration](#system-registration)
5. [SSH Configuration](#ssh-configuration)
6. [Creating Sync Groups](#creating-sync-groups)
7. [Verification](#verification)
8. [Dashboard Access](#dashboard-access)

---

## Prerequisites

### System Requirements

- **Witness Server**: A system to run the ZFS Sync service
  - Python 3.9+ (for native installation) OR Docker
  - 512MB RAM minimum (1GB recommended)
  - 100MB disk space for application + database
  - Network connectivity to all ZFS systems

- **ZFS Systems**: Systems with ZFS pools to synchronize
  - ZFS installed and configured
  - Network connectivity to witness server
  - SSH access (for automated sync execution)
  - Ability to run `zfs send` and `zfs receive` commands

### Network Topology Planning

Before installation, plan your network topology:

1. **Witness Server Location**
   - Should be accessible from all ZFS systems
   - Consider network latency and reliability
   - Can run on a dedicated server or alongside other services

2. **Network Connectivity**
   - All ZFS systems must reach the witness server (HTTP/HTTPS)
   - Systems need SSH access to each other for sync operations
   - Consider firewall rules and security groups

3. **Port Requirements**
   - Witness server: Port 8000 (default, configurable)
   - SSH: Port 22 (default, configurable per system)

---

## Installation Options

### Option 1: Docker Installation (Recommended)

Docker installation is recommended for production deployments as it provides:
- Consistent environment across different systems
- Easy updates and maintenance
- Built-in health checks and logging
- Isolation from host system

#### Quick Start with Docker

```bash
# 1. Create persistent data directory
sudo mkdir -p /var/lib/zfs-sync
sudo chown -R 1001:1001 /var/lib/zfs-sync
sudo chmod 755 /var/lib/zfs-sync

# 2. Clone or download the repository
git clone <repository-url>
cd zfs_sync

# 3. Start the service
docker-compose up -d

# 4. Verify it's running
curl http://localhost:8000/api/v1/health
```

#### Production Docker Setup

For production, use PostgreSQL instead of SQLite:

```bash
# 1. Set environment variables
export POSTGRES_PASSWORD=your-secure-password-here
export ZFS_SYNC_SECRET_KEY=your-secret-key-here

# 2. Start with production configuration
docker-compose -f docker-compose.yml -f docker-compose.prod.yml up -d

# 3. Verify health
curl http://localhost:8000/api/v1/health
```

**See [README.md](../README.md) for detailed Docker deployment instructions.**

### Option 2: Native Python Installation

Native installation is useful for development or when Docker is not available.

```bash
# 1. Install Python dependencies
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt

# 2. Run the service
python -m zfs_sync
```

**See [QUICK_START.md](../QUICK_START.md) for detailed native installation instructions.**

### Decision Matrix: SQLite vs PostgreSQL

| Factor | SQLite | PostgreSQL |
|--------|--------|------------|
| **Deployment Size** | < 10 systems | 10+ systems |
| **Concurrent Access** | Single process | Multiple processes |
| **Backup Complexity** | File copy | `pg_dump` required |
| **Performance** | Good for small deployments | Better for large deployments |
| **Setup Complexity** | Simple (no setup) | Requires database server |
| **Recommended For** | Development, small deployments | Production, large deployments |

**Recommendation**: Start with SQLite for simplicity. Migrate to PostgreSQL if you experience performance issues or need concurrent access.

---

## Initial Configuration

### Configuration File Setup

1. **Copy the example configuration**:

```bash
cp config/zfs_sync.yaml.example config/zfs_sync.yaml
```

2. **Edit the configuration file** (if needed):

```yaml
# Application settings
app_name: "zfs-sync"
app_version: "0.2.0"
debug: false
log_level: "INFO"

# Server configuration
host: "0.0.0.0"  # Listen on all interfaces
port: 8000

# Database configuration
# For SQLite (default):
# database_url: "sqlite:////var/lib/zfs-sync/zfs_sync.db"

# For PostgreSQL:
# database_url: "postgresql://user:password@localhost:5432/zfs_sync"

# Sync settings
default_sync_interval_seconds: 3600  # 1 hour
heartbeat_timeout_seconds: 300  # 5 minutes
```

### Environment Variables

Configuration can also be set via environment variables (highest priority):

```bash
export ZFS_SYNC_DATABASE_URL="sqlite:////var/lib/zfs-sync/zfs_sync.db"
export ZFS_SYNC_HOST="0.0.0.0"
export ZFS_SYNC_PORT="8000"
export ZFS_SYNC_LOG_LEVEL="INFO"
export ZFS_SYNC_SECRET_KEY="your-secret-key-here"
```

**Configuration Priority** (highest to lowest):
1. Environment variables
2. Configuration file (`config/zfs_sync.yaml`)
3. Default values

### Verify Configuration

After starting the service, verify it's working:

```bash
# Check health endpoint
curl http://localhost:8000/api/v1/health

# Expected response:
# {"status":"healthy","version":"0.2.0","database":"connected"}
```

---

## System Registration

A "system" in ZFS Sync represents a physical or virtual machine with ZFS pools that you want to synchronize.

### Register Your First System

Use the API to register systems. You can use the interactive API documentation at `http://localhost:8000/docs` or use curl:

```bash
curl -X POST "http://localhost:8000/api/v1/systems" \
  -H "Content-Type: application/json" \
  -d '{
    "hostname": "backup-server-01",
    "platform": "linux",
    "connectivity_status": "online"
  }'
```

**Response Example**:

```json
{
  "id": "123e4567-e89b-12d3-a456-426614174000",
  "hostname": "backup-server-01",
  "platform": "linux",
  "api_key": "abc123def456ghi789jkl012mno345pq",
  "connectivity_status": "online",
  "created_at": "2024-01-15T10:00:00Z"
}
```

**⚠️ IMPORTANT**: Save the `api_key` from the response! You'll need it for all authenticated API requests from this system. The API key is only shown once during registration.

### Register Additional Systems

Repeat the registration process for each ZFS system you want to synchronize. Each system gets its own unique API key.

**Example for multiple systems**:

```bash
# System 1
curl -X POST "http://localhost:8000/api/v1/systems" \
  -H "Content-Type: application/json" \
  -d '{"hostname": "primary-server", "platform": "linux"}'

# System 2
curl -X POST "http://localhost:8000/api/v1/systems" \
  -H "Content-Type: application/json" \
  -d '{"hostname": "backup-server", "platform": "linux"}'

# System 3
curl -X POST "http://localhost:8000/api/v1/systems" \
  -H "Content-Type: application/json" \
  -d '{"hostname": "remote-backup", "platform": "freebsd"}'
```

### List Registered Systems

Verify all systems are registered:

```bash
curl http://localhost:8000/api/v1/systems
```

### Update System Information

You can update system information later (e.g., to add SSH details):

```bash
curl -X PUT "http://localhost:8000/api/v1/systems/{system_id}" \
  -H "X-API-Key: your-api-key-here" \
  -H "Content-Type: application/json" \
  -d '{
    "hostname": "backup-server-01-updated",
    "platform": "linux"
  }'
```

---

## SSH Configuration

SSH configuration enables ZFS Sync to generate ready-to-execute sync commands. Systems can then execute these commands automatically.

### Prerequisites

- SSH key-based authentication must be configured between systems
- SSH keys should have proper permissions (600 for private keys)
- Systems must have network connectivity for SSH

### Step 1: Generate SSH Key Pair (if needed)

On each system that will receive sync commands:

```bash
# Generate SSH key (if you don't have one)
ssh-keygen -t ed25519 -f ~/.ssh/zfs_sync_key -N ""

# Or use RSA if ed25519 is not available
ssh-keygen -t rsa -b 4096 -f ~/.ssh/zfs_sync_key -N ""
```

### Step 2: Distribute Public Keys

Copy the public key to all systems that need to receive snapshots:

```bash
# On source system, copy public key to target system
ssh-copy-id -i ~/.ssh/zfs_sync_key.pub user@target-system

# Or manually:
cat ~/.ssh/zfs_sync_key.pub | ssh user@target-system "mkdir -p ~/.ssh && cat >> ~/.ssh/authorized_keys"
```

### Step 3: Test SSH Connectivity

Test SSH access from each system to others:

```bash
# Test SSH connection
ssh -i ~/.ssh/zfs_sync_key -p 22 user@target-system "zfs list"

# If using custom port:
ssh -i ~/.ssh/zfs_sync_key -p 2222 user@target-system "zfs list"
```

### Step 4: Register SSH Details with ZFS Sync

Update each system's registration with SSH connection details:

```bash
curl -X PUT "http://localhost:8000/api/v1/systems/{system_id}" \
  -H "X-API-Key: your-api-key-here" \
  -H "Content-Type: application/json" \
  -d '{
    "ssh_hostname": "backup-server-01.internal",
    "ssh_user": "zfsadmin",
    "ssh_port": 22
  }'
```

**SSH Configuration Fields**:

- `ssh_hostname`: Hostname or IP address for SSH connections
- `ssh_user`: Username for SSH authentication
- `ssh_port`: SSH port (default: 22)

**Note**: The `ssh_hostname` can differ from the system's `hostname` field. This is useful when systems have different internal/external hostnames.

### Step 5: Verify SSH Configuration

After registering SSH details, sync instructions will include ready-to-execute commands:

```bash
curl -X GET "http://localhost:8000/api/v1/sync/instructions/{system_id}?include_commands=true" \
  -H "X-API-Key: your-api-key-here"
```

The response will include `sync_command` fields with complete commands:

```json
{
  "actions": [
    {
      "action_type": "sync_snapshot",
      "sync_command": "ssh -p 22 zfsadmin@backup-server-01.internal 'zfs send tank/data@backup-20240115-120000' | zfs receive -F tank/data",
      "source_ssh_hostname": "backup-server-01.internal",
      "source_ssh_user": "zfsadmin",
      "source_ssh_port": 22
    }
  ]
}
```

---

## Creating Sync Groups

A sync group defines which systems should maintain synchronized snapshots. ZFS Sync supports two sync modes:

1. **Bidirectional Sync** (default): All systems in the group sync with each other
2. **Directional Sync** (hub-and-spoke): One hub system pushes to all other systems

### Bidirectional Sync Groups

Use bidirectional sync when you want all systems to stay in sync with each other (e.g., backup clusters, redundant storage).

**Example: Three-System Backup Cluster**

```bash
curl -X POST "http://localhost:8000/api/v1/sync-groups" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "production-backup-cluster",
    "description": "Production backup cluster with bidirectional sync",
    "enabled": true,
    "directional": false,
    "sync_interval_seconds": 3600,
    "system_ids": [
      "system-id-1",
      "system-id-2",
      "system-id-3"
    ]
  }'
```

**How it works**:
- System 1 syncs missing snapshots from Systems 2 and 3
- System 2 syncs missing snapshots from Systems 1 and 3
- System 3 syncs missing snapshots from Systems 1 and 2
- All systems eventually converge to the same snapshot set

### Directional Sync Groups (Hub-and-Spoke)

Use directional sync when you have a source system that distributes snapshots to multiple replicas (e.g., master-replica, content distribution).

**Example: Master-to-Replica Distribution**

```bash
curl -X POST "http://localhost:8000/api/v1/sync-groups" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "master-to-replicas",
    "description": "Hub-and-spoke distribution from master to replicas",
    "enabled": true,
    "directional": true,
    "hub_system_id": "master-system-id",
    "sync_interval_seconds": 1800,
    "system_ids": [
      "master-system-id",
      "replica-1-id",
      "replica-2-id",
      "replica-3-id"
    ]
  }'
```

**How it works**:
- Master system (hub) pushes snapshots TO all replicas
- Replicas only receive from master (no cross-sync between replicas)
- Master acts as source of truth for data distribution

**Important**: The `hub_system_id` must be one of the systems in `system_ids`.

### Multiple Dataset Patterns

ZFS Sync uses **pool-agnostic dataset comparison**, meaning systems with different pool names can sync the same logical dataset.

**Example Scenario**:
- System A: Pool `hqs10p1`, Dataset `L1S4DAT1`
- System B: Pool `hqs7p1`, Dataset `L1S4DAT1`

These are recognized as the same logical dataset and will sync correctly, even though the pool names differ.

**Creating a sync group for multiple datasets**:

```bash
# The sync group automatically handles all datasets reported by systems
# No special configuration needed - just add systems to the group
curl -X POST "http://localhost:8000/api/v1/sync-groups" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "multi-dataset-sync",
    "enabled": true,
    "system_ids": ["system-1", "system-2"]
  }'
```

When systems report snapshots for different datasets, ZFS Sync will:
- Group snapshots by dataset name (ignoring pool differences)
- Generate sync instructions for each dataset independently
- Preserve pool information in sync commands

### Sync Group Configuration Options

| Field | Type | Description | Default |
|-------|------|-------------|---------|
| `name` | string | Unique name for the sync group | Required |
| `description` | string | Human-readable description | Optional |
| `enabled` | boolean | Enable/disable sync group | `true` |
| `directional` | boolean | Use hub-and-spoke mode | `false` |
| `hub_system_id` | UUID | Hub system for directional sync | Required if `directional=true` |
| `sync_interval_seconds` | integer | How often to check for sync needs | `3600` |
| `system_ids` | array | List of system UUIDs in the group | Required |

### List Sync Groups

Verify sync groups are created:

```bash
curl http://localhost:8000/api/v1/sync-groups
```

### Update Sync Groups

You can update sync groups (e.g., add/remove systems, change settings):

```bash
curl -X PUT "http://localhost:8000/api/v1/sync-groups/{group_id}" \
  -H "Content-Type: application/json" \
  -d '{
    "enabled": false,
    "sync_interval_seconds": 7200,
    "system_ids": ["system-1", "system-2", "system-4"]  # Added system-4, removed system-3
  }'
```

---

## Verification

After setting up systems and sync groups, verify everything is working correctly.

### 1. Check System Health

```bash
# Check all systems
curl http://localhost:8000/api/v1/systems/health/all

# Check only online systems
curl http://localhost:8000/api/v1/systems/health/online

# Check only offline systems
curl http://localhost:8000/api/v1/systems/health/offline
```

### 2. Report Test Snapshots

From each ZFS system, report some test snapshots:

```bash
# On System 1
curl -X POST "http://localhost:8000/api/v1/snapshots" \
  -H "X-API-Key: system-1-api-key" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "test-snapshot-001",
    "pool": "tank",
    "dataset": "tank/data",
    "timestamp": "2024-01-15T12:00:00Z",
    "size": 1073741824,
    "system_id": "system-1-id"
  }'
```

### 3. Check Sync Instructions

Request sync instructions for a system:

```bash
curl -X GET "http://localhost:8000/api/v1/sync/instructions/{system_id}?include_commands=true" \
  -H "X-API-Key: system-api-key"
```

You should see sync actions if snapshots differ between systems.

### 4. Check Sync Status

Check the sync status for a sync group:

```bash
curl http://localhost:8000/api/v1/sync/groups/{group_id}/status
```

### 5. Verify Dashboard

Open the web dashboard in your browser:

```
http://localhost:8000/
```

You should see:
- All registered systems
- Sync groups
- System health status
- Recent activity

**See [DASHBOARD_GUIDE.md](DASHBOARD_GUIDE.md) for detailed dashboard usage.**

---

## Dashboard Access

The ZFS Sync web dashboard provides a user-friendly interface for monitoring and managing your sync environment.

### Accessing the Dashboard

1. **Open your web browser** and navigate to:

   ```
   http://your-server-ip:8000/
   ```

   Or if running locally:

   ```
   http://localhost:8000/
   ```

2. **Dashboard Features**:
   - **Overview**: System status, sync group summary, recent activity
   - **Systems**: List of all registered systems with health status
   - **Sync Groups**: Sync group configuration and status
   - **Conflicts**: Detected conflicts and resolution options
   - **Statistics**: Charts and trends

3. **Real-time Updates**: The dashboard uses Server-Sent Events (SSE) to update automatically. Look for the connection status indicator in the top-right corner.

### Dashboard Limitations

Currently, the dashboard is **read-only**. To create or modify systems and sync groups, use the API endpoints directly or the interactive API documentation at `http://localhost:8000/docs`.

**See [DASHBOARD_GUIDE.md](DASHBOARD_GUIDE.md) for complete dashboard documentation.**

---

## Next Steps

After completing setup:

1. **Set up automation** - See [OPERATIONS_GUIDE.md](OPERATIONS_GUIDE.md) for automation examples
2. **Monitor operations** - Use the dashboard to monitor sync status
3. **Configure reporting** - Set up scripts to report snapshots automatically
4. **Review troubleshooting** - Familiarize yourself with [TROUBLESHOOTING_GUIDE.md](TROUBLESHOOTING_GUIDE.md)

---

## Related Documentation

- [OPERATIONS_GUIDE.md](OPERATIONS_GUIDE.md) - Daily operations and maintenance
- [TROUBLESHOOTING_GUIDE.md](TROUBLESHOOTING_GUIDE.md) - Issue resolution
- [DASHBOARD_GUIDE.md](DASHBOARD_GUIDE.md) - Web dashboard usage
- [HOW_TO_USE.md](../HOW_TO_USE.md) - API usage examples
- [README.md](../README.md) - Project overview and deployment details
