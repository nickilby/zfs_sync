# ZFS Sync Troubleshooting Guide

A systematic guide for diagnosing and resolving issues with ZFS Sync.

## Table of Contents

1. [Diagnostic Steps](#diagnostic-steps)
2. [Common Issues](#common-issues)
3. [Log Analysis](#log-analysis)
4. [API Debugging](#api-debugging)
5. [Database Inspection](#database-inspection)
6. [Getting Help](#getting-help)

---

## Diagnostic Steps

Follow these steps systematically when troubleshooting issues:

### Step 1: Verify Service Status

```bash
# Check if service is running
docker ps | grep zfs-sync
# Or for native installation:
systemctl status zfs-sync

# Check health endpoint
curl http://localhost:8000/api/v1/health
```

**Expected Response**:
```json
{"status":"healthy","version":"0.2.0","database":"connected"}
```

### Step 2: Check System Connectivity

```bash
# Check all systems
curl http://localhost:8000/api/v1/systems/health/all

# Check specific system
curl http://localhost:8000/api/v1/systems/{system_id}/health
```

### Step 3: Review Recent Logs

```bash
# Docker logs
docker-compose logs --tail=100 zfs-sync

# Or native installation
tail -100 /var/log/zfs-sync.log
```

### Step 4: Test API Endpoints

```bash
# Test basic endpoints
curl http://localhost:8000/api/v1/health
curl http://localhost:8000/api/v1/systems
curl http://localhost:8000/api/v1/sync-groups
```

### Step 5: Verify Database Connection

```bash
# SQLite
sqlite3 /var/lib/zfs-sync/zfs_sync.db "SELECT COUNT(*) FROM systems;"

# PostgreSQL
psql -U zfs_sync -d zfs_sync -c "SELECT COUNT(*) FROM systems;"
```

---

## Common Issues

### Installation/Startup Issues

#### Database Connection Failures

**Symptoms**:
- Service won't start
- Error: "unable to open database file"
- Error: "database is locked"

**Solutions**:

1. **Check database file permissions**:
   ```bash
   ls -lah /var/lib/zfs-sync/
   # Should be owned by UID 1001 (container user) or your user

   # Fix permissions
   sudo chown -R 1001:1001 /var/lib/zfs-sync
   sudo chmod 755 /var/lib/zfs-sync
   ```

2. **Verify database URL matches volume mount**:
   ```bash
   # If using Docker volume mount /var/lib/zfs-sync:/data
   # Database URL should be: sqlite:////data/zfs_sync.db

   # Check environment variable
   docker exec zfs-sync env | grep DATABASE_URL
   ```

3. **Check if database file exists**:
   ```bash
   ls -lah /var/lib/zfs-sync/zfs_sync.db
   # If missing, service will create it on startup
   ```

4. **For SQLite "database is locked"**:
   ```bash
   # Check for other processes accessing database
   lsof /var/lib/zfs-sync/zfs_sync.db

   # If using WAL mode, check for stale lock files
   ls -lah /var/lib/zfs-sync/zfs_sync.db-*
   ```

#### Port Conflicts

**Symptoms**:
- Error: "Address already in use"
- Service won't start on port 8000

**Solutions**:

1. **Find process using port 8000**:
   ```bash
   # Linux
   sudo lsof -i :8000
   # Or
   sudo netstat -tulpn | grep 8000

   # macOS
   lsof -i :8000
   ```

2. **Change port**:
   ```bash
   # Set environment variable
   export ZFS_SYNC_PORT=8080

   # Or in docker-compose.yml
   environment:
     - ZFS_SYNC_PORT=8080
   ports:
     - "8080:8080"
   ```

#### Permission Problems

**Symptoms**:
- "Permission denied" errors
- Cannot write to database or logs

**Solutions**:

1. **Check container user**:
   ```bash
   docker exec zfs-sync id
   # Should show: uid=1001(zfssync) gid=1001(zfssync)
   ```

2. **Fix directory permissions**:
   ```bash
   sudo chown -R 1001:1001 /var/lib/zfs-sync
   sudo chmod 755 /var/lib/zfs-sync
   ```

3. **Check log directory permissions**:
   ```bash
   sudo chown -R 1001:1001 /path/to/logs
   sudo chmod 755 /path/to/logs
   ```

### System Registration Issues

#### API Key Problems

**Symptoms**:
- "API key required" error
- "Invalid API key" error
- Cannot authenticate requests

**Solutions**:

1. **Verify API key is included in request**:
   ```bash
   # Correct format
   curl -H "X-API-Key: your-api-key-here" http://localhost:8000/api/v1/systems

   # Check header name (must be X-API-Key, not API-Key or api-key)
   ```

2. **Regenerate API key**:
   ```bash
   curl -X POST "http://localhost:8000/api/v1/systems/{system_id}/api-key/rotate" \
     -H "X-API-Key: current-api-key"
   ```

3. **Verify system exists**:
   ```bash
   curl http://localhost:8000/api/v1/systems/{system_id}
   ```

#### System Not Appearing in Dashboard

**Symptoms**:
- System registered but not visible in dashboard
- Dashboard shows "No systems"

**Solutions**:

1. **Verify system is registered**:
   ```bash
   curl http://localhost:8000/api/v1/systems
   ```

2. **Check dashboard API connection**:
   - Open browser developer console (F12)
   - Check for JavaScript errors
   - Verify API calls are successful

3. **Check SSE connection**:
   - Look for SSE status indicator in dashboard (top-right)
   - Should be green/connected
   - If red/disconnected, check server logs

4. **Hard refresh browser** (Ctrl+F5 or Cmd+Shift+R)

### Sync Issues

#### Snapshots Not Syncing

**Symptoms**:
- Snapshots exist on source but not syncing to target
- Sync instructions show actions but sync doesn't happen

**Solutions**:

1. **Check sync group is enabled**:
   ```bash
   curl http://localhost:8000/api/v1/sync-groups/{group_id}
   # Verify "enabled": true
   ```

2. **Verify systems are in sync group**:
   ```bash
   curl http://localhost:8000/api/v1/sync-groups/{group_id}
   # Check system_ids array includes both systems
   ```

3. **Check sync instructions**:
   ```bash
   curl -X GET "http://localhost:8000/api/v1/sync/instructions/{system_id}" \
     -H "X-API-Key: api-key"
   ```

4. **Verify snapshots are reported**:
   ```bash
   curl "http://localhost:8000/api/v1/snapshots?system_id={system_id}" \
     -H "X-API-Key: api-key"
   ```

5. **Check for conflicts**:
   ```bash
   curl http://localhost:8000/api/v1/conflicts/{sync_group_id}
   ```

6. **Verify dataset names match** (pool-agnostic):
   - System A: `pool1/dataset1`
   - System B: `pool2/dataset1`
   - These should sync (same dataset name, different pools)

#### Incremental Sync Failures

**Symptoms**:
- Full syncs work but incremental fails
- Error: "incremental source snapshot not found"

**Solutions**:

1. **Verify base snapshot exists on target**:
   ```bash
   # On target system
   zfs list -t snapshot pool/dataset
   ```

2. **Check snapshot naming**:
   - Snapshot names must match exactly (case-sensitive)
   - Verify snapshot names are normalized correctly

3. **Check sync instructions for incremental base**:
   ```bash
   curl -X GET "http://localhost:8000/api/v1/sync/instructions/{system_id}?include_commands=true" \
     -H "X-API-Key: api-key" | jq '.actions[] | {snapshot: .snapshot_name, incremental_base: .incremental_base}'
   ```

4. **Manually verify incremental send**:
   ```bash
   # On source system
   zfs send -i base-snapshot pool/dataset@new-snapshot
   ```

#### Pool/Dataset Name Mismatches

**Symptoms**:
- Snapshots not matching between systems
- Sync instructions show wrong pool names

**Solutions**:

1. **Understand pool-agnostic matching**:
   - ZFS Sync matches datasets by dataset name, not pool name
   - `pool1/dataset1` matches `pool2/dataset1`
   - Pool information is preserved in sync commands

2. **Verify dataset names**:
   ```bash
   # On each system
   zfs list -t snapshot -o name
   ```

3. **Check sync instructions**:
   ```bash
   curl -X GET "http://localhost:8000/api/v1/sync/instructions/{system_id}?include_diagnostics=true" \
     -H "X-API-Key: api-key"
   ```

4. **Review dataset grouping**:
   - ZFS Sync groups snapshots by dataset name
   - Ensure dataset names are consistent across systems

### SSH Connection Issues

#### Authentication Failures

**Symptoms**:
- "Permission denied (publickey)" errors
- SSH commands fail in sync instructions

**Solutions**:

1. **Verify SSH key exists**:
   ```bash
   ls -lah ~/.ssh/zfs_sync_key
   # Should show permissions 600
   ```

2. **Test SSH connection manually**:
   ```bash
   ssh -i ~/.ssh/zfs_sync_key -v user@target-system
   ```

3. **Check SSH key permissions**:
   ```bash
   chmod 600 ~/.ssh/zfs_sync_key
   chmod 644 ~/.ssh/zfs_sync_key.pub
   ```

4. **Verify public key on target**:
   ```bash
   # On target system
   cat ~/.ssh/authorized_keys | grep zfs_sync
   ```

5. **Check SSH configuration**:
   ```bash
   # On source system
   ssh -i ~/.ssh/zfs_sync_key -F ~/.ssh/config user@target-system
   ```

#### Network Connectivity Problems

**Symptoms**:
- "Connection refused" errors
- "Host unreachable" errors
- Timeouts

**Solutions**:

1. **Test network connectivity**:
   ```bash
   ping target-system
   telnet target-system 22
   ```

2. **Verify SSH hostname in system registration**:
   ```bash
   curl http://localhost:8000/api/v1/systems/{system_id} | jq '.ssh_hostname'
   ```

3. **Check firewall rules**:
   ```bash
   # On target system
   sudo ufw status
   sudo iptables -L -n
   ```

4. **Test SSH with verbose output**:
   ```bash
   ssh -i ~/.ssh/zfs_sync_key -v user@target-system
   ```

#### Permission Denied Errors

**Symptoms**:
- "Permission denied" when executing ZFS commands via SSH
- ZFS commands fail with permission errors

**Solutions**:

1. **Verify user has ZFS permissions**:
   ```bash
   # On target system
   sudo zfs allow -l user zfs_sync_user create,mount,send,receive tank
   ```

2. **Check sudo configuration** (if using sudo):
   ```bash
   # Ensure user can run ZFS commands without password
   sudo visudo
   # Add: user ALL=(ALL) NOPASSWD: /usr/sbin/zfs, /usr/sbin/zpool
   ```

3. **Test ZFS commands directly**:
   ```bash
   # On target system
   zfs list
   zfs receive -F pool/dataset
   ```

### Dashboard Issues

#### Dashboard Not Loading

**Symptoms**:
- Blank page
- 404 errors
- Dashboard doesn't appear

**Solutions**:

1. **Verify service is running**:
   ```bash
   curl http://localhost:8000/api/v1/health
   ```

2. **Check dashboard URL**:
   - Should be: `http://localhost:8000/`
   - Not: `http://localhost:8000/dashboard/`

3. **Check browser console** (F12):
   - Look for JavaScript errors
   - Check network tab for failed requests

4. **Verify static files are served**:
   ```bash
   curl http://localhost:8000/static/dashboard/index.html
   ```

5. **Check CORS settings** (if accessing from different domain):
   - Verify CORS is configured in application settings

#### Data Not Updating

**Symptoms**:
- Dashboard shows stale data
- Changes not reflected in dashboard

**Solutions**:

1. **Check SSE connection**:
   - Look for SSE status indicator (top-right)
   - Should be green/connected
   - If disconnected, check server logs

2. **Hard refresh browser** (Ctrl+F5)

3. **Check API directly**:
   ```bash
   curl http://localhost:8000/api/v1/systems
   # Compare with dashboard data
   ```

4. **Verify SSE endpoint**:
   ```bash
   curl -N http://localhost:8000/api/v1/events
   # Should stream events
   ```

#### SSE Connection Failures

**Symptoms**:
- SSE status indicator shows disconnected
- Dashboard doesn't update automatically

**Solutions**:

1. **Check server logs**:
   ```bash
   docker-compose logs zfs-sync | grep -i sse
   ```

2. **Verify SSE endpoint**:
   ```bash
   curl -N http://localhost:8000/api/v1/events
   ```

3. **Check browser console**:
   - Look for SSE connection errors
   - Check for CORS issues

4. **Test with different browser**:
   - Some browsers have SSE limitations

### Performance Issues

#### Slow Sync Operations

**Symptoms**:
- Syncs take a long time
- High latency in API responses

**Solutions**:

1. **Check database performance**:
   ```bash
   # SQLite
   sqlite3 /var/lib/zfs-sync/zfs_sync.db "ANALYZE;"

   # Check database size
   ls -lh /var/lib/zfs-sync/zfs_sync.db
   ```

2. **Review sync interval**:
   - Reduce sync frequency if not critical
   - Increase interval for less critical data

3. **Check network bandwidth**:
   ```bash
   # Monitor network during sync
   iftop -i eth0
   ```

4. **Optimize database** (see [OPERATIONS_GUIDE.md](OPERATIONS_GUIDE.md#database-maintenance))

#### High CPU/Memory Usage

**Symptoms**:
- Service using excessive resources
- System becomes slow

**Solutions**:

1. **Check resource usage**:
   ```bash
   # Docker
   docker stats zfs-sync

   # Native
   top -p $(pgrep -f zfs_sync)
   ```

2. **Review log level**:
   - Set to INFO or WARNING instead of DEBUG
   - Reduces logging overhead

3. **Check for stuck processes**:
   ```bash
   ps aux | grep zfs_sync
   ```

4. **Review database queries**:
   - Check for inefficient queries in logs
   - Consider database optimization

#### Database Performance

**Symptoms**:
- Slow API responses
- Database queries timeout

**Solutions**:

1. **SQLite optimization**:
   ```sql
   PRAGMA journal_mode = WAL;
   PRAGMA cache_size = -10000;
   PRAGMA synchronous = NORMAL;
   ```

2. **PostgreSQL optimization**:
   - Increase shared_buffers
   - Tune work_mem
   - Add indexes if needed

3. **Database maintenance**:
   ```bash
   # Vacuum and analyze
   sqlite3 /var/lib/zfs-sync/zfs_sync.db "VACUUM; ANALYZE;"
   ```

4. **Consider migration to PostgreSQL** for large deployments

---

## Log Analysis

### Understanding Log Messages

ZFS Sync uses structured logging. Common log patterns:

#### INFO Messages
- Normal operations: system registration, snapshot reporting, sync operations
- Example: `Created system: backup-server-01 (123e4567...)`

#### WARNING Messages
- Non-critical issues: orphan datasets, missing snapshots
- Example: `Orphan dataset detected: pool/dataset on system X`

#### ERROR Messages
- Critical issues: database errors, API failures
- Example: `Failed to generate API key for system X`

#### DEBUG Messages
- Detailed diagnostic information (only if log_level=DEBUG)

### Common Log Patterns

#### Database Errors
```
ERROR: Failed to create system: database is locked
```
**Solution**: Check for concurrent database access, consider PostgreSQL

#### API Key Issues
```
ERROR: Invalid API key for system X
```
**Solution**: Verify API key, regenerate if needed

#### Sync Failures
```
ERROR: Sync failed for dataset pool/dataset: snapshot not found
```
**Solution**: Verify snapshot exists on source system

### Log Locations

- **Docker**: `docker-compose logs zfs-sync`
- **Native**: `/var/log/zfs-sync/zfs_sync.log`
- **Systemd**: `journalctl -u zfs-sync`

---

## API Debugging

### Using curl for Testing

#### Test Health Endpoint
```bash
curl -v http://localhost:8000/api/v1/health
```

#### Test System Registration
```bash
curl -v -X POST "http://localhost:8000/api/v1/systems" \
  -H "Content-Type: application/json" \
  -d '{"hostname":"test-system","platform":"linux"}'
```

#### Test Authenticated Endpoint
```bash
curl -v -X GET "http://localhost:8000/api/v1/systems" \
  -H "X-API-Key: your-api-key-here"
```

### Using Postman/HTTPie

#### HTTPie Example
```bash
# Install HTTPie
pip install httpie

# Test endpoint
http GET http://localhost:8000/api/v1/systems X-API-Key:your-api-key
```

### Common API Errors

#### 401 Unauthorized
- Missing or invalid API key
- Solution: Verify API key header name and value

#### 404 Not Found
- Resource doesn't exist
- Solution: Verify UUIDs are correct

#### 409 Conflict
- Resource already exists (e.g., duplicate hostname)
- Solution: Use different hostname or update existing system

#### 500 Internal Server Error
- Server-side error
- Solution: Check server logs for details

---

## Database Inspection

### SQLite Queries

#### List All Systems
```sql
SELECT id, hostname, platform, connectivity_status, last_seen
FROM systems;
```

#### List All Snapshots
```sql
SELECT s.name, s.pool, s.dataset, s.timestamp, sys.hostname
FROM snapshots s
JOIN systems sys ON s.system_id = sys.id
ORDER BY s.timestamp DESC
LIMIT 100;
```

#### Check Sync States
```sql
SELECT
    sg.name as sync_group,
    sys.hostname,
    ss.dataset,
    ss.status,
    ss.last_sync
FROM sync_states ss
JOIN sync_groups sg ON ss.sync_group_id = sg.id
JOIN systems sys ON ss.system_id = sys.id
WHERE ss.status != 'in_sync';
```

#### Find Orphaned Snapshots
```sql
SELECT s.*, sys.hostname
FROM snapshots s
JOIN systems sys ON s.system_id = sys.id
WHERE s.id NOT IN (
    SELECT DISTINCT snapshot_id FROM sync_states WHERE snapshot_id IS NOT NULL
);
```

#### Database Statistics
```sql
-- Count by table
SELECT 'systems' as table_name, COUNT(*) as count FROM systems
UNION ALL
SELECT 'snapshots', COUNT(*) FROM snapshots
UNION ALL
SELECT 'sync_groups', COUNT(*) FROM sync_groups
UNION ALL
SELECT 'sync_states', COUNT(*) FROM sync_states;
```

### PostgreSQL Queries

Same queries work for PostgreSQL, just use `psql`:

```bash
psql -U zfs_sync -d zfs_sync -c "SELECT COUNT(*) FROM systems;"
```

---

## Getting Help

### Information to Collect

When seeking help, collect the following information:

1. **ZFS Sync Version**:
   ```bash
   curl http://localhost:8000/api/v1/health | jq '.version'
   ```

2. **System Information**:
   ```bash
   uname -a
   docker --version  # if using Docker
   python --version  # if native installation
   ```

3. **Configuration**:
   - Database type (SQLite/PostgreSQL)
   - Number of systems
   - Number of sync groups
   - Sync interval settings

4. **Error Messages**:
   - Full error message from logs
   - API error responses
   - Browser console errors (if dashboard issue)

5. **Recent Changes**:
   - What changed before the issue appeared
   - System updates, configuration changes, etc.

6. **Logs**:
   - Last 100 lines of application logs
   - Relevant error messages

### Log Collection Script

```bash
#!/bin/bash
# Collect troubleshooting information

echo "=== ZFS Sync Troubleshooting Information ==="
echo "Date: $(date)"
echo ""

echo "=== Version ==="
curl -s http://localhost:8000/api/v1/health | jq '.'
echo ""

echo "=== System Health ==="
curl -s http://localhost:8000/api/v1/systems/health/all | jq '.'
echo ""

echo "=== Recent Logs (last 50 lines) ==="
docker-compose logs --tail=50 zfs-sync 2>/dev/null || tail -50 /var/log/zfs-sync.log
echo ""

echo "=== Database Statistics ==="
sqlite3 /var/lib/zfs-sync/zfs_sync.db "SELECT 'systems' as table_name, COUNT(*) as count FROM systems UNION ALL SELECT 'snapshots', COUNT(*) FROM snapshots UNION ALL SELECT 'sync_groups', COUNT(*) FROM sync_groups UNION ALL SELECT 'sync_states', COUNT(*) FROM sync_states;" 2>/dev/null || echo "Cannot access database"
```

### Where to Get Help

1. **Check Documentation**:
   - [SETUP_GUIDE.md](SETUP_GUIDE.md)
   - [OPERATIONS_GUIDE.md](OPERATIONS_GUIDE.md)
   - [README.md](../README.md)

2. **Review Logs**: Most issues can be resolved by reviewing logs

3. **API Documentation**: Check interactive docs at `http://localhost:8000/docs`

4. **GitHub Issues**: If using GitHub, check existing issues or create new one

---

## Related Documentation

- [SETUP_GUIDE.md](SETUP_GUIDE.md) - Initial setup and configuration
- [OPERATIONS_GUIDE.md](OPERATIONS_GUIDE.md) - Daily operations and maintenance
- [DASHBOARD_GUIDE.md](DASHBOARD_GUIDE.md) - Web dashboard usage
- [HOW_TO_USE.md](../HOW_TO_USE.md) - API usage examples
