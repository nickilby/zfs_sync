# Docker Configuration

This directory contains Docker-related configuration files.

## Log Rotation

The ZFS Sync application includes multiple layers of log rotation:

### 1. Application-Level Rotation (Python)

The application uses Python's `RotatingFileHandler` for automatic log rotation:

- **Max file size**: 10MB (configurable via `log_max_bytes` setting)
- **Backup count**: 5 files (configurable via `log_backup_count` setting)
- **Location**: `/logs/zfs_sync.log` in Docker container

When the log file reaches the maximum size, it's rotated:

- `zfs_sync.log` → `zfs_sync.log.1`
- `zfs_sync.log.1` → `zfs_sync.log.2`
- etc.

Oldest files beyond the backup count are automatically deleted.

### 2. Docker-Level Rotation

Docker Compose is configured with log rotation for container stdout/stderr:

- **Max size**: 10MB per file
- **Max files**: 3 files
- **Driver**: `json-file`

This handles logs from `docker logs` command and container output.

### 3. System-Level Rotation (Optional)

For additional control, you can use the provided `logrotate.conf` file on the host system:

1. Copy the configuration to your system's logrotate directory:

   ```bash
   sudo cp docker/logrotate.conf /etc/logrotate.d/zfs-sync
   ```

1. The configuration will:

   - Rotate logs daily
   - Keep 7 days of logs
   - Compress old logs
   - Use `copytruncate` to avoid interrupting the application

## Configuration

Log rotation settings can be configured via:

1. **Environment variables**:

   ```bash
   ZFS_SYNC_LOG_FILE=/logs/zfs_sync.log
   ZFS_SYNC_LOG_MAX_BYTES=10485760  # 10MB in bytes
   ZFS_SYNC_LOG_BACKUP_COUNT=5
   ```

1. **Configuration file** (`config/zfs_sync.yaml`):

   ```yaml
   log_file: "/logs/zfs_sync.log"
   log_max_bytes: 10485760  # 10MB
   log_backup_count: 5
   ```

## Log File Location

In Docker, logs are written to `/logs/zfs_sync.log` inside the container, which is typically mounted to `./logs/zfs_sync.log` on the host via the `docker-compose.yml` volume mount.

## Monitoring Logs

View application logs:

```bash
# View current log file
tail -f logs/zfs_sync.log

# View rotated logs
ls -lh logs/zfs_sync.log*

# View via Docker
docker logs -f zfs-sync
```
