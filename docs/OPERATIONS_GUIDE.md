# ZFS Sync Operations Guide

A guide for technical users running ZFS Sync in production environments.

## Table of Contents

1. [Daily Operations](#daily-operations)
2. [Automation](#automation)
3. [Maintenance Tasks](#maintenance-tasks)
4. [Performance Tuning](#performance-tuning)
5. [Backup and Recovery](#backup-and-recovery)

---

## Daily Operations

### Monitoring System Health

#### Via Dashboard

1. Open the dashboard: `http://your-server:8000/`
2. Navigate to the **Systems** view
3. Check the health status indicator for each system:
   - **Green/Online**: System is healthy and sending heartbeats
   - **Red/Offline**: System hasn't sent a heartbeat recently
   - **Gray/Unknown**: Status not yet determined

#### Via API

```bash
# Check all systems
curl http://your-server:8000/api/v1/systems/health/all

# Check only online systems
curl http://your-server:8000/api/v1/systems/health/online

# Check only offline systems
curl http://your-server:8000/api/v1/systems/health/offline

# Check specific system
curl http://your-server:8000/api/v1/systems/{system_id}/health
```

**Expected Response**:

```json
{
  "system_id": "123e4567-e89b-12d3-a456-426614174000",
  "status": "online",
  "last_seen": "2024-01-15T14:30:00Z",
  "heartbeat_age_seconds": 45
}
```

### Checking Sync Status

#### Via Dashboard

1. Navigate to **Sync Groups** view
2. Click on a sync group to see detailed status
3. Review sync states and any conflicts

#### Via API

```bash
# Get sync status for a sync group
curl http://your-server:8000/api/v1/sync/groups/{group_id}/status

# Get sync instructions for a system
curl -X GET "http://your-server:8000/api/v1/sync/instructions/{system_id}" \
  -H "X-API-Key: your-api-key"
```

### Handling Sync Failures

When a sync operation fails:

1. **Check the logs**:
   ```bash
   # Docker logs
   docker-compose logs zfs-sync | grep ERROR

   # Or if running natively
   tail -f /var/log/zfs-sync.log | grep ERROR
   ```

2. **Verify system connectivity**:
   ```bash
   # Check if system is online
   curl http://your-server:8000/api/v1/systems/{system_id}/health
   ```

3. **Test SSH connectivity** (if using SSH):
   ```bash
   ssh -i ~/.ssh/zfs_sync_key user@target-system "zfs list"
   ```

4. **Check sync instructions again**:
   ```bash
   curl -X GET "http://your-server:8000/api/v1/sync/instructions/{system_id}?include_commands=true" \
     -H "X-API-Key: your-api-key"
   ```

5. **Manually execute sync** (if needed):
   ```bash
   # Use the sync_command from the instructions
   ssh -p 22 user@source-system 'zfs send pool/dataset@snapshot' | zfs receive -F pool/dataset
   ```

6. **Update sync state** after manual sync:
   ```bash
   curl -X POST "http://your-server:8000/api/v1/sync/states" \
     -H "X-API-Key: your-api-key" \
     -H "Content-Type: application/json" \
     -d '{
       "sync_group_id": "group-id",
       "snapshot_id": "snapshot-id",
       "system_id": "system-id",
       "status": "in_sync"
     }'
   ```

**See [TROUBLESHOOTING_GUIDE.md](TROUBLESHOOTING_GUIDE.md) for detailed troubleshooting steps.**

### Managing API Keys

#### Viewing API Keys

API keys are only shown once during system registration. To view or regenerate:

```bash
# Generate a new API key (rotates the old one)
curl -X POST "http://your-server:8000/api/v1/systems/{system_id}/api-key/rotate" \
  -H "X-API-Key: current-api-key"

# Response includes new API key
# {
#   "api_key": "new-api-key-here",
#   "system_id": "system-id"
# }
```

#### Revoking API Keys

```bash
# Revoke API key (system will need to generate a new one)
curl -X DELETE "http://your-server:8000/api/v1/systems/{system_id}/api-key" \
  -H "X-API-Key: current-api-key"
```

#### Best Practices

- Store API keys securely (use a password manager or secrets management system)
- Rotate API keys periodically (e.g., every 90 days)
- Use different API keys for different systems
- Never commit API keys to version control

---

## Automation

### Snapshot Reporting Automation

Systems should automatically report snapshots when they are created. Here are example automation scripts:

#### Cron Job for Snapshot Reporting

Create a script `/usr/local/bin/zfs-sync-report.sh`:

```bash
#!/bin/bash

# Configuration
API_URL="http://your-zfs-sync-server:8000/api/v1"
API_KEY="your-api-key-here"
SYSTEM_ID="your-system-id-here"

# Get all snapshots from this system
zfs list -t snapshot -H -o name,creation,used,referenced | while IFS=$'\t' read -r name creation used referenced; do
    # Extract pool, dataset, and snapshot name
    pool=$(echo "$name" | cut -d'/' -f1)
    dataset=$(echo "$name" | cut -d'@' -f1)
    snap_name=$(echo "$name" | cut -d'@' -f2)

    # Convert creation time to ISO format
    timestamp=$(date -d "$creation" -Iseconds 2>/dev/null || date -j -f "%a %b %d %H:%M %Y" "$creation" "+%Y-%m-%dT%H:%M:%SZ" 2>/dev/null || echo "$(date -Iseconds)")

    # Convert size to bytes (used field is in human-readable format)
    size_bytes=$(echo "$used" | awk '{
        if ($0 ~ /[0-9]+K/) {print int($0) * 1024}
        else if ($0 ~ /[0-9]+M/) {print int($0) * 1024 * 1024}
        else if ($0 ~ /[0-9]+G/) {print int($0) * 1024 * 1024 * 1024}
        else if ($0 ~ /[0-9]+T/) {print int($0) * 1024 * 1024 * 1024 * 1024}
        else {print int($0)}
    }')

    # Report snapshot
    curl -s -X POST "$API_URL/snapshots" \
      -H "X-API-Key: $API_KEY" \
      -H "Content-Type: application/json" \
      -d "{
        \"name\": \"$snap_name\",
        \"pool\": \"$pool\",
        \"dataset\": \"$dataset\",
        \"timestamp\": \"$timestamp\",
        \"size\": $size_bytes,
        \"system_id\": \"$SYSTEM_ID\"
      }" > /dev/null
done

# Send heartbeat
curl -s -X POST "$API_URL/systems/$SYSTEM_ID/heartbeat" \
  -H "X-API-Key: $API_KEY" > /dev/null

echo "$(date): Snapshot report completed"
```

Make it executable:

```bash
chmod +x /usr/local/bin/zfs-sync-report.sh
```

Add to crontab (run every hour):

```bash
# Add to crontab
crontab -e

# Add this line:
0 * * * * /usr/local/bin/zfs-sync-report.sh >> /var/log/zfs-sync-report.log 2>&1
```

#### Systemd Timer for Snapshot Reporting

Create `/etc/systemd/system/zfs-sync-report.service`:

```ini
[Unit]
Description=ZFS Sync Snapshot Reporting
After=network.target

[Service]
Type=oneshot
ExecStart=/usr/local/bin/zfs-sync-report.sh
User=root
StandardOutput=journal
StandardError=journal
```

Create `/etc/systemd/system/zfs-sync-report.timer`:

```ini
[Unit]
Description=ZFS Sync Snapshot Reporting Timer
Requires=zfs-sync-report.service

[Timer]
OnCalendar=hourly
Persistent=true

[Install]
WantedBy=timers.target
```

Enable and start:

```bash
systemctl daemon-reload
systemctl enable zfs-sync-report.timer
systemctl start zfs-sync-report.timer
```

### Sync Execution Automation

Create a script to automatically execute sync instructions:

```bash
#!/bin/bash

# Configuration
API_URL="http://your-zfs-sync-server:8000/api/v1"
API_KEY="your-api-key-here"
SYSTEM_ID="your-system-id-here"

# Get sync instructions
INSTRUCTIONS=$(curl -s -X GET "$API_URL/sync/instructions/$SYSTEM_ID?include_commands=true" \
  -H "X-API-Key: $API_KEY")

# Check if there are actions
ACTION_COUNT=$(echo "$INSTRUCTIONS" | jq -r '.action_count // 0')

if [ "$ACTION_COUNT" -eq 0 ]; then
    echo "$(date): No sync actions needed"
    exit 0
fi

echo "$(date): Found $ACTION_COUNT sync actions"

# Process each action
echo "$INSTRUCTIONS" | jq -r '.actions[] | @json' | while read -r action; do
    ACTION_TYPE=$(echo "$action" | jq -r '.action_type')
    SYNC_COMMAND=$(echo "$action" | jq -r '.sync_command // empty')
    SNAPSHOT_ID=$(echo "$action" | jq -r '.snapshot_id // empty')
    SYNC_GROUP_ID=$(echo "$action" | jq -r '.sync_group_id')
    DATASET=$(echo "$action" | jq -r '.dataset')

    if [ -z "$SYNC_COMMAND" ]; then
        echo "Warning: No sync command for action $ACTION_TYPE"
        continue
    fi

    echo "Executing: $SYNC_COMMAND"

    # Execute sync command
    if eval "$SYNC_COMMAND"; then
        echo "Sync successful for $DATASET"

        # Update sync state if snapshot_id is available
        if [ -n "$SNAPSHOT_ID" ] && [ "$SNAPSHOT_ID" != "null" ]; then
            curl -s -X POST "$API_URL/sync/states" \
              -H "X-API-Key: $API_KEY" \
              -H "Content-Type: application/json" \
              -d "{
                \"sync_group_id\": \"$SYNC_GROUP_ID\",
                \"snapshot_id\": \"$SNAPSHOT_ID\",
                \"system_id\": \"$SYSTEM_ID\",
                \"status\": \"in_sync\"
              }" > /dev/null
        fi
    else
        echo "ERROR: Sync failed for $DATASET"
        # Update sync state to error
        if [ -n "$SNAPSHOT_ID" ] && [ "$SNAPSHOT_ID" != "null" ]; then
            curl -s -X POST "$API_URL/sync/states" \
              -H "X-API-Key: $API_KEY" \
              -H "Content-Type: application/json" \
              -d "{
                \"sync_group_id\": \"$SYNC_GROUP_ID\",
                \"snapshot_id\": \"$SNAPSHOT_ID\",
                \"system_id\": \"$SYSTEM_ID\",
                \"status\": \"error\"
              }" > /dev/null
        fi
    fi
done

echo "$(date): Sync execution completed"
```

Save as `/usr/local/bin/zfs-sync-execute.sh` and add to crontab (run every 15 minutes):

```bash
chmod +x /usr/local/bin/zfs-sync-execute.sh

# Add to crontab
*/15 * * * * /usr/local/bin/zfs-sync-execute.sh >> /var/log/zfs-sync-execute.log 2>&1
```

### Python Automation Example

For more complex automation, use Python:

```python
#!/usr/bin/env python3
"""ZFS Sync automation script."""

import requests
import subprocess
import json
from datetime import datetime

API_URL = "http://your-zfs-sync-server:8000/api/v1"
API_KEY = "your-api-key-here"
SYSTEM_ID = "your-system-id-here"

def report_snapshots():
    """Report all snapshots from this system."""
    # Get snapshots using zfs command
    result = subprocess.run(
        ["zfs", "list", "-t", "snapshot", "-H", "-o", "name,creation,used"],
        capture_output=True,
        text=True
    )

    snapshots = []
    for line in result.stdout.strip().split('\n'):
        if not line:
            continue
        name, creation, used = line.split('\t')
        pool = name.split('/')[0]
        dataset = name.split('@')[0]
        snap_name = name.split('@')[1]

        snapshots.append({
            "name": snap_name,
            "pool": pool,
            "dataset": dataset,
            "timestamp": creation,  # Convert to ISO format as needed
            "size": parse_size(used),
            "system_id": SYSTEM_ID
        })

    # Report snapshots
    response = requests.post(
        f"{API_URL}/snapshots/batch",
        headers={"X-API-Key": API_KEY, "Content-Type": "application/json"},
        json={"snapshots": snapshots}
    )
    response.raise_for_status()
    print(f"Reported {len(snapshots)} snapshots")

def execute_sync():
    """Get and execute sync instructions."""
    response = requests.get(
        f"{API_URL}/sync/instructions/{SYSTEM_ID}?include_commands=true",
        headers={"X-API-Key": API_KEY}
    )
    response.raise_for_status()
    instructions = response.json()

    if instructions.get("action_count", 0) == 0:
        print("No sync actions needed")
        return

    for action in instructions.get("actions", []):
        sync_command = action.get("sync_command")
        if not sync_command:
            continue

        print(f"Executing: {sync_command}")
        result = subprocess.run(sync_command, shell=True, capture_output=True, text=True)

        if result.returncode == 0:
            print(f"Sync successful for {action.get('dataset')}")
            # Update sync state
            update_sync_state(action, "in_sync")
        else:
            print(f"Sync failed: {result.stderr}")
            update_sync_state(action, "error")

def update_sync_state(action, status):
    """Update sync state after sync operation."""
    if not action.get("snapshot_id"):
        return

    requests.post(
        f"{API_URL}/sync/states",
        headers={"X-API-Key": API_KEY, "Content-Type": "application/json"},
        json={
            "sync_group_id": action["sync_group_id"],
            "snapshot_id": action["snapshot_id"],
            "system_id": SYSTEM_ID,
            "status": status
        }
    )

def send_heartbeat():
    """Send heartbeat to ZFS Sync."""
    requests.post(
        f"{API_URL}/systems/{SYSTEM_ID}/heartbeat",
        headers={"X-API-Key": API_KEY}
    )

if __name__ == "__main__":
    try:
        report_snapshots()
        execute_sync()
        send_heartbeat()
        print(f"{datetime.now()}: Automation completed successfully")
    except Exception as e:
        print(f"ERROR: {e}")
        exit(1)
```

### Integration with Existing Backup Workflows

ZFS Sync can integrate with existing backup tools:

#### Sanoid Integration

Add to your Sanoid configuration to report snapshots after creation:

```bash
# In /etc/sanoid/sanoid.conf or similar
[tank/data]
    # ... existing sanoid config ...
    post_snapshot = curl -X POST "http://zfs-sync-server:8000/api/v1/snapshots" -H "X-API-Key: $API_KEY" -H "Content-Type: application/json" -d '{"name":"%s","pool":"tank","dataset":"tank/data","timestamp":"$(date -Iseconds)","system_id":"$SYSTEM_ID"}'
```

#### ZFS Event Daemon (zed) Integration

Configure zed to report snapshots when they're created:

```bash
# In /etc/zfs/zed.d/zed.rc or similar
# Add script to report snapshots to ZFS Sync
```

---

## Maintenance Tasks

### Database Maintenance

#### SQLite Database

For SQLite databases, periodic maintenance helps keep performance optimal:

```bash
# Vacuum database (reclaim space, optimize)
sqlite3 /var/lib/zfs-sync/zfs_sync.db "VACUUM;"

# Analyze database (update statistics)
sqlite3 /var/lib/zfs-sync/zfs_sync.db "ANALYZE;"

# Check database integrity
sqlite3 /var/lib/zfs-sync/zfs_sync.db "PRAGMA integrity_check;"
```

**Automated maintenance script**:

```bash
#!/bin/bash
# /usr/local/bin/zfs-sync-db-maintenance.sh

DB_PATH="/var/lib/zfs-sync/zfs_sync.db"

if [ ! -f "$DB_PATH" ]; then
    echo "Database not found: $DB_PATH"
    exit 1
fi

# Vacuum
sqlite3 "$DB_PATH" "VACUUM;"

# Analyze
sqlite3 "$DB_PATH" "ANALYZE;"

# Integrity check
INTEGRITY=$(sqlite3 "$DB_PATH" "PRAGMA integrity_check;")
if [ "$INTEGRITY" != "ok" ]; then
    echo "WARNING: Database integrity check failed: $INTEGRITY"
    exit 1
fi

echo "$(date): Database maintenance completed"
```

Add to crontab (run weekly):

```bash
0 2 * * 0 /usr/local/bin/zfs-sync-db-maintenance.sh >> /var/log/zfs-sync-maintenance.log 2>&1
```

#### PostgreSQL Database

For PostgreSQL, use standard maintenance:

```bash
# Vacuum
psql -U zfs_sync -d zfs_sync -c "VACUUM ANALYZE;"

# Or use pg_cron for automated maintenance
```

### Log Rotation and Cleanup

ZFS Sync logs are automatically rotated when using Docker. For native installations:

```bash
# Configure logrotate
cat > /etc/logrotate.d/zfs-sync <<EOF
/var/log/zfs-sync/*.log {
    daily
    rotate 7
    compress
    delaycompress
    missingok
    notifempty
    create 0644 zfssync zfssync
}
EOF
```

### Updating Systems in Sync Groups

To add a system to an existing sync group:

```bash
# Get current sync group
CURRENT_GROUP=$(curl -s "http://your-server:8000/api/v1/sync-groups/{group_id}")

# Extract current system IDs and add new one
NEW_SYSTEM_IDS=$(echo "$CURRENT_GROUP" | jq -r '.system_ids + ["new-system-id"]')

# Update sync group
curl -X PUT "http://your-server:8000/api/v1/sync-groups/{group_id}" \
  -H "Content-Type: application/json" \
  -d "{
    \"system_ids\": $NEW_SYSTEM_IDS
  }"
```

To remove a system from a sync group:

```bash
# Get current sync group and remove system
CURRENT_GROUP=$(curl -s "http://your-server:8000/api/v1/sync-groups/{group_id}")
NEW_SYSTEM_IDS=$(echo "$CURRENT_GROUP" | jq -r '.system_ids | map(select(. != "system-to-remove-id"))')

# Update sync group
curl -X PUT "http://your-server:8000/api/v1/sync-groups/{group_id}" \
  -H "Content-Type: application/json" \
  -d "{
    \"system_ids\": $NEW_SYSTEM_IDS
  }"
```

### Removing Decommissioned Systems

When a system is decommissioned:

1. **Remove from all sync groups**:
   ```bash
   # List all sync groups
   GROUPS=$(curl -s "http://your-server:8000/api/v1/sync-groups")

   # For each group, remove the system
   # (Use the update method above)
   ```

2. **Delete the system**:
   ```bash
   curl -X DELETE "http://your-server:8000/api/v1/systems/{system_id}"
   ```

3. **Clean up snapshots** (optional):
   ```bash
   # Snapshots are automatically cleaned up when system is deleted
   # Or manually delete snapshots for the system
   ```

---

## Performance Tuning

### Sync Interval Optimization

Adjust sync intervals based on your needs:

- **Frequent syncs** (every 15-30 minutes): For critical data requiring near-real-time sync
- **Standard syncs** (every 1-2 hours): For most production workloads
- **Infrequent syncs** (every 6-24 hours): For less critical backups

```bash
# Update sync interval for a sync group
curl -X PUT "http://your-server:8000/api/v1/sync-groups/{group_id}" \
  -H "Content-Type: application/json" \
  -d '{
    "sync_interval_seconds": 1800
  }'
```

### Database Tuning for Large Deployments

#### SQLite Tuning

For SQLite with many systems and snapshots:

```sql
-- Increase page size (requires database recreation)
PRAGMA page_size = 4096;

-- Enable WAL mode (better concurrency)
PRAGMA journal_mode = WAL;

-- Increase cache size
PRAGMA cache_size = -10000;  -- 10MB cache
```

#### PostgreSQL Tuning

For PostgreSQL, adjust `postgresql.conf`:

```ini
# Increase shared buffers
shared_buffers = 256MB

# Increase work memory
work_mem = 16MB

# Enable connection pooling
max_connections = 100
```

### Network Bandwidth Considerations

When syncing large datasets:

1. **Schedule syncs during off-peak hours** (if possible)
2. **Use incremental syncs** (ZFS Sync automatically uses incremental when possible)
3. **Limit concurrent syncs** (execute syncs sequentially rather than in parallel)
4. **Monitor network usage** and adjust sync frequency accordingly

---

## Backup and Recovery

### Backing Up ZFS Sync Database

#### SQLite Backup

```bash
# Simple file copy (stop service first for consistency)
docker-compose stop zfs-sync
cp /var/lib/zfs-sync/zfs_sync.db /backup/zfs_sync_$(date +%Y%m%d).db
docker-compose start zfs-sync

# Or use SQLite backup command (can run while service is running)
sqlite3 /var/lib/zfs-sync/zfs_sync.db ".backup /backup/zfs_sync_$(date +%Y%m%d).db"
```

**Automated backup script**:

```bash
#!/bin/bash
# /usr/local/bin/zfs-sync-backup.sh

BACKUP_DIR="/backup/zfs-sync"
DB_PATH="/var/lib/zfs-sync/zfs_sync.db"
RETENTION_DAYS=30

mkdir -p "$BACKUP_DIR"

# Create backup
BACKUP_FILE="$BACKUP_DIR/zfs_sync_$(date +%Y%m%d_%H%M%S).db"
sqlite3 "$DB_PATH" ".backup '$BACKUP_FILE'"

# Compress backup
gzip "$BACKUP_FILE"

# Remove old backups
find "$BACKUP_DIR" -name "zfs_sync_*.db.gz" -mtime +$RETENTION_DAYS -delete

echo "$(date): Backup completed: $BACKUP_FILE.gz"
```

#### PostgreSQL Backup

```bash
# Full backup
pg_dump -U zfs_sync zfs_sync > /backup/zfs_sync_$(date +%Y%m%d).sql

# Compressed backup
pg_dump -U zfs_sync zfs_sync | gzip > /backup/zfs_sync_$(date +%Y%m%d).sql.gz
```

### Disaster Recovery Procedures

#### Scenario 1: Witness Server Failure

1. **Restore database backup**:
   ```bash
   # SQLite
   cp /backup/zfs_sync_latest.db /var/lib/zfs-sync/zfs_sync.db

   # PostgreSQL
   psql -U zfs_sync zfs_sync < /backup/zfs_sync_latest.sql
   ```

2. **Restart ZFS Sync service**:
   ```bash
   docker-compose restart zfs-sync
   ```

3. **Verify systems reconnect**:
   ```bash
   curl http://your-server:8000/api/v1/systems/health/all
   ```

#### Scenario 2: System Re-registration

If a system needs to be re-registered (e.g., after hardware replacement):

1. **Register the new system**:
   ```bash
   curl -X POST "http://your-server:8000/api/v1/systems" \
     -H "Content-Type: application/json" \
     -d '{
       "hostname": "new-system-hostname",
       "platform": "linux"
     }'
   ```

2. **Add to sync groups** (if using same hostname, may auto-join):
   ```bash
   # Update sync groups to include new system ID
   ```

3. **Report existing snapshots**:
   ```bash
   # Run snapshot reporting script to populate database
   ```

4. **Verify sync instructions**:
   ```bash
   curl -X GET "http://your-server:8000/api/v1/sync/instructions/{new-system-id}" \
     -H "X-API-Key: new-api-key"
   ```

#### Scenario 3: Database Corruption

If database becomes corrupted:

1. **Stop ZFS Sync service**
2. **Restore from backup**
3. **If no backup, recreate database** (systems will need to re-register):
   ```bash
   # SQLite
   rm /var/lib/zfs-sync/zfs_sync.db
   # Service will recreate on startup
   ```

4. **Re-register all systems**
5. **Recreate sync groups**
6. **Systems report snapshots again**

### Recovery Testing

Regularly test your backup and recovery procedures:

1. **Monthly backup verification**: Restore backup to test environment
2. **Quarterly disaster recovery drill**: Simulate complete failure and recovery
3. **Document recovery times**: Track how long recovery takes

---

## Related Documentation

- [SETUP_GUIDE.md](SETUP_GUIDE.md) - Initial setup and configuration
- [TROUBLESHOOTING_GUIDE.md](TROUBLESHOOTING_GUIDE.md) - Issue resolution
- [DASHBOARD_GUIDE.md](DASHBOARD_GUIDE.md) - Web dashboard usage
- [HOW_TO_USE.md](../HOW_TO_USE.md) - API usage examples
