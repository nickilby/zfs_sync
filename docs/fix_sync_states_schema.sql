-- Fix sync_states table schema: Change from snapshot_id to dataset
-- This script drops and recreates the sync_states table with the new schema
--
-- Note: This will delete all existing sync_states, but that's safe because:
-- - sync_states are ephemeral (track current sync status, not historical data)
-- - They will be automatically regenerated when sync coordination runs
--
-- IMPORTANT: This preserves all other data (systems, snapshots, sync_groups)

-- Step 1: Drop the existing sync_states table
DROP TABLE IF EXISTS sync_states;

-- Step 2: Recreate sync_states table with new schema (dataset instead of snapshot_id)
-- Note: GUID columns are stored as CHAR(36) in SQLite, JSON is stored as TEXT
CREATE TABLE sync_states (
    id CHAR(36) PRIMARY KEY,
    sync_group_id CHAR(36) NOT NULL,
    dataset VARCHAR(255) NOT NULL,
    system_id CHAR(36) NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'out_of_sync',
    last_sync TIMESTAMP,
    last_check TIMESTAMP,
    error_message TEXT,
    metadata TEXT DEFAULT '{}',
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (sync_group_id) REFERENCES sync_groups(id),
    FOREIGN KEY (system_id) REFERENCES systems(id)
);

-- Step 3: Create index on dataset
CREATE INDEX ix_sync_states_dataset ON sync_states(dataset);

-- Step 4: Create index on sync_group_id (if not exists)
CREATE INDEX IF NOT EXISTS ix_sync_states_sync_group_id ON sync_states(sync_group_id);

-- Step 5: Create index on system_id (if not exists)
CREATE INDEX IF NOT EXISTS ix_sync_states_system_id ON sync_states(system_id);

-- Step 6: Create index on status (if not exists)
CREATE INDEX IF NOT EXISTS ix_sync_states_status ON sync_states(status);
