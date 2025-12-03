# Database Schema Update: Sync States

## Problem

The `sync_states` table schema was changed from using `snapshot_id` to `dataset`. The database needs to be updated to match the new code.

## Solution Options

Since `sync_states` are ephemeral (they track current sync status and are automatically regenerated), you have two options:

### Option 1: Simple SQL Script (Recommended - Fastest)

Run the SQL script to drop and recreate the `sync_states` table:

```bash
# From inside the Docker container or on the host
sqlite3 /data/zfs_sync.db < docs/fix_sync_states_schema.sql
```

Or if running directly on the host:

```bash
sqlite3 /path/to/zfs_sync.db < docs/fix_sync_states_schema.sql
```

**What this does:**

- Drops the old `sync_states` table
- Creates a new `sync_states` table with `dataset` column instead of `snapshot_id`
- Preserves all other data (systems, snapshots, sync_groups)

**Note:** All existing sync_states will be deleted, but they'll be automatically regenerated when sync coordination runs.

### Option 2: Alembic Migration

If you prefer to use Alembic migrations:

```bash
# Run the migration
alembic upgrade head
```

**What this does:**

- Clears all existing sync_states
- Drops the `snapshot_id` column
- Adds the `dataset` column
- Creates the index on `dataset`

## Verification

After running either option, verify the schema is correct:

```bash
sqlite3 /data/zfs_sync.db ".schema sync_states"
```

You should see `dataset VARCHAR(255)` instead of `snapshot_id`.

## Important Notes

- **No data loss for important tables**: Systems, snapshots, and sync_groups are all preserved
- **Sync states will be regenerated**: The sync scheduler will automatically recreate sync_states as needed
- **Backup recommended**: Always backup your database before schema changes:

  ```bash
  cp /data/zfs_sync.db /data/zfs_sync.db.backup
  ```
