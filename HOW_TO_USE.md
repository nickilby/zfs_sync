# How to Use ZFS Sync

A beginner-friendly guide to using the ZFS Sync witness service for keeping snapshots synchronized across multiple systems.

## Table of Contents

1. [What is ZFS Sync?](#what-is-zfs-sync)
2. [Getting Started](#getting-started)
3. [Step-by-Step Setup](#step-by-step-setup)
4. [Using the System](#using-the-system)
5. [Common Tasks](#common-tasks)
6. [Troubleshooting](#troubleshooting)

---

## What is ZFS Sync?

ZFS Sync is a **witness service** that helps keep your ZFS snapshots synchronized across multiple computers or storage systems. Think of it as a central coordinator that:

- Tracks which snapshots exist on each system
- Detects when snapshots are missing
- Tells systems what needs to be synchronized
- Monitors the health of all connected systems

**Why use it?** If you have multiple ZFS systems (like backup servers, remote storage, etc.) and want to ensure they all have the same snapshots, ZFS Sync coordinates this for you.

---

## Getting Started

### Prerequisites

Before you begin, you need:

- Python 3.9 or higher installed
- Access to the systems you want to synchronize
- Network connectivity between the witness server and your ZFS systems

### Installation

#### Option 1: Local Installation (Recommended)

1. **Clone or download the repository:**
   ```bash
   git clone <repository-url>
   cd zfs_sync
   ```

2. **Set up virtual environment and install dependencies:**
   ```bash
   # Run the setup script (creates venv and installs dependencies)
   ./setup.sh
   
   # Or manually:
   python3 -m venv venv
   source venv/bin/activate
   pip install --upgrade pip
   pip install -r requirements.txt
   ```

3. **Activate the virtual environment (if not already active):**

   ```bash
   source venv/bin/activate
   ```

4. **Start the server:**

   ```bash
   python -m zfs_sync
   ```

   The server will start on `http://0.0.0.0:8000` (accessible from any network interface)

#### Option 2: Docker Installation

1. **Build the Docker image:**

   ```bash
   docker-compose build
   ```

2. **Start the container:**

   ```bash
   docker-compose up -d
   ```

3. **View logs:**

   ```bash
   docker-compose logs -f
   ```

---

## Step-by-Step Setup

### Step 1: Access the Web Interface

Once the server is running, open your web browser and go to:

```
http://localhost:8000/docs
```

This opens the **interactive API documentation** where you can test all features.

### Step 2: Register Your First System

A "system" is a computer or server that has ZFS pools and snapshots.

1. In the API docs, find the **Systems** section
2. Click on `POST /api/v1/systems`
3. Click "Try it out"
4. Fill in the form:

   ```json
   {
     "hostname": "backup-server-01",
     "platform": "linux",
     "connectivity_status": "online"
   }
   ```

5. Click "Execute"

**Important:** Save the `api_key` from the response! You'll need it for all future requests from this system.

**Example Response:**

```json
{
  "id": "123e4567-e89b-12d3-a456-426614174000",
  "hostname": "backup-server-01",
  "platform": "linux",
  "api_key": "your-secret-api-key-here",
  ...
}
```

### Step 3: Register Additional Systems

Repeat Step 2 for each system you want to synchronize. Each system gets its own unique API key.

### Step 4: Create a Sync Group

A sync group tells ZFS Sync which systems should stay synchronized with each other.

1. Find the **Sync Groups** section in the API docs
2. Click on `POST /api/v1/sync-groups`
3. Click "Try it out"
4. Fill in the form:

   ```json
   {
     "name": "Production Backup Group",
     "enabled": true,
     "sync_interval_seconds": 3600,
     "system_ids": [
       "system-id-1",
       "system-id-2"
     ]
   }
   ```

5. Click "Execute"

**Note:** Use the `id` values from the systems you registered in Step 2.

### Step 5: Report Snapshots

Now your systems need to tell ZFS Sync what snapshots they have.

1. Find the **Snapshots** section
2. Click on `POST /api/v1/snapshots`
3. Click "Try it out"
4. Fill in snapshot information:

   ```json
   {
     "name": "backup-20240115-120000",
     "pool": "tank",
     "dataset": "tank/data",
     "timestamp": "2024-01-15T12:00:00Z",
     "size": 1073741824,
     "system_id": "your-system-id"
   }
   ```

5. Click "Execute"

**Tip:** You can report multiple snapshots at once using `POST /api/v1/snapshots/batch`

---

## Using the System

### Daily Operations

#### 1. Send Heartbeat (Keep System Online)

Your systems should regularly send a heartbeat to show they're alive:

```bash
curl -X POST "http://localhost:8000/api/v1/systems/{system_id}/heartbeat" \
  -H "X-API-Key: your-api-key-here"
```

**When to do this:** Set up a cron job or scheduled task to run this every 5 minutes.

#### 2. Report New Snapshots

Whenever a new snapshot is created on your system, report it:

```bash
curl -X POST "http://localhost:8000/api/v1/snapshots" \
  -H "X-API-Key: your-api-key-here" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "backup-20240116-120000",
    "pool": "tank",
    "dataset": "tank/data",
    "timestamp": "2024-01-16T12:00:00Z",
    "size": 1073741824,
    "system_id": "your-system-id"
  }'
```

#### 3. Check What Needs Syncing

Ask ZFS Sync what snapshots your system needs to sync:

```bash
curl -X GET "http://localhost:8000/api/v1/sync/instructions/{system_id}" \
  -H "X-API-Key: your-api-key-here"
```

**Response Example:**

```json
{
  "system_id": "...",
  "actions": [
    {
      "action_type": "sync_snapshot",
      "pool": "tank",
      "dataset": "tank/data",
      "snapshot_name": "backup-20240115-120000",
      "source_system_id": "...",
      "priority": 25
    }
  ]
}
```

This tells you which snapshots to copy from other systems.

#### 4. Update Sync Status

After syncing a snapshot, tell ZFS Sync it's done:

```bash
curl -X POST "http://localhost:8000/api/v1/sync/states" \
  -H "X-API-Key: your-api-key-here" \
  -H "Content-Type: application/json" \
  -d '{
    "sync_group_id": "sync-group-id",
    "snapshot_id": "snapshot-id",
    "system_id": "your-system-id",
    "status": "in_sync"
  }'
```

---

## Common Tasks

### Task 1: Check System Health

See which systems are online or offline:

```bash
# All systems
curl http://localhost:8000/api/v1/systems/health/all

# Only online systems
curl http://localhost:8000/api/v1/systems/health/online

# Only offline systems
curl http://localhost:8000/api/v1/systems/health/offline
```

### Task 2: Compare Snapshots Between Systems

See what's different between two systems:

```bash
curl "http://localhost:8000/api/v1/snapshots/differences?system_id_1={id1}&system_id_2={id2}&pool=tank&dataset=tank/data"
```

### Task 3: Find Missing Snapshots

Identify gaps in your snapshot sequences:

```bash
curl "http://localhost:8000/api/v1/snapshots/gaps?pool=tank&dataset=tank/data&system_ids={id1}&system_ids={id2}"
```

### Task 4: View Snapshot History

See the history of snapshots for a system:

```bash
curl "http://localhost:8000/api/v1/snapshots/history/{system_id}?days=30"
```

### Task 5: Get Sync Status Summary

Check the overall sync status for a sync group:

```bash
curl http://localhost:8000/api/v1/sync/groups/{group_id}/status
```

---

## Automation Script Example

Here's a simple bash script that automates snapshot reporting and heartbeat:

```bash
#!/bin/bash

# Configuration
API_URL="http://localhost:8000/api/v1"
API_KEY="your-api-key-here"
SYSTEM_ID="your-system-id"

# Get all snapshots from this system
SNAPSHOTS=$(zfs list -t snapshot -H -o name,creation,used,referenced)

# Report each snapshot
while IFS=$'\t' read -r name creation used referenced; do
    # Extract pool, dataset, and snapshot name
    pool=$(echo $name | cut -d'/' -f1)
    dataset=$(echo $name | cut -d'@' -f1)
    snap_name=$(echo $name | cut -d'@' -f2)
    
    # Convert creation time to ISO format
    timestamp=$(date -d "$creation" -Iseconds)
    
    # Report snapshot
    curl -X POST "$API_URL/snapshots" \
      -H "X-API-Key: $API_KEY" \
      -H "Content-Type: application/json" \
      -d "{
        \"name\": \"$snap_name\",
        \"pool\": \"$pool\",
        \"dataset\": \"$dataset\",
        \"timestamp\": \"$timestamp\",
        \"system_id\": \"$SYSTEM_ID\"
      }"
done <<< "$SNAPSHOTS"

# Send heartbeat
curl -X POST "$API_URL/systems/$SYSTEM_ID/heartbeat" \
  -H "X-API-Key: $API_KEY"

# Get sync instructions
curl -X GET "$API_URL/sync/instructions/$SYSTEM_ID" \
  -H "X-API-Key: $API_KEY"
```

Save this as `zfs_sync_report.sh`, make it executable (`chmod +x zfs_sync_report.sh`), and add it to your crontab:

```bash
# Run every hour
0 * * * * /path/to/zfs_sync_report.sh
```

---

## Troubleshooting

### Problem: "API key required" error

**Solution:** Make sure you're including the API key in the request header:
```bash
-H "X-API-Key: your-api-key-here"
```

### Problem: System shows as "offline"

**Solution:** 

1. Check if the system is sending heartbeats regularly
2. Verify the heartbeat timeout setting (default: 300 seconds)
3. Send a heartbeat manually to test

### Problem: Can't see snapshots from other systems

**Solution:**

1. Make sure all systems are in the same sync group
2. Verify snapshots are being reported correctly
3. Check the sync group is enabled

### Problem: "System not found" error

**Solution:**

1. Verify you're using the correct system ID
2. Check the system exists: `GET /api/v1/systems/{system_id}`
3. Make sure you registered the system first

### Problem: Server won't start

**Solution:**

1. Check if port 8000 is already in use
2. Verify all dependencies are installed: `pip install -r requirements.txt`
3. Check the logs for error messages

---

## Quick Reference

### Important Endpoints

| Endpoint | Purpose | Auth Required |
|----------|---------|---------------|
| `POST /api/v1/systems` | Register a system | No |
| `POST /api/v1/systems/{id}/heartbeat` | Send heartbeat | Yes |
| `POST /api/v1/snapshots` | Report snapshot | Yes |
| `GET /api/v1/sync/instructions/{id}` | Get sync instructions | Yes |
| `GET /api/v1/systems/health/all` | Check all systems | No |

### Status Values

- `in_sync` - Snapshot is synchronized
- `out_of_sync` - Snapshot needs syncing
- `syncing` - Currently being synced
- `conflict` - Conflict detected
- `error` - Error occurred

### Connectivity Status

- `online` - System is responding (heartbeat within timeout)
- `offline` - System hasn't sent heartbeat recently
- `unknown` - Status not yet determined

---

## Next Steps

1. **Set up automation:** Create scripts to automatically report snapshots and send heartbeats
2. **Monitor health:** Regularly check system health endpoints
3. **Review sync status:** Periodically check sync group status to ensure everything is synchronized
4. **Scale up:** Add more systems and sync groups as needed

---

## Getting Help

- Check the API documentation at `http://localhost:8000/docs`
- Review the main README.md for technical details
- Check server logs for error messages

---

**Remember:** The API key is like a password - keep it secure and don't share it!

