#!/bin/bash
# ZFS Sync Executor Script Template
# This script fetches sync instructions from the witness service and executes them

set -euo pipefail

# Configuration
WITNESS_API_URL="${WITNESS_API_URL:-http://localhost:8000}"
SYSTEM_ID="${SYSTEM_ID:-}"
API_KEY="${API_KEY:-}"
LOG_FILE="${LOG_FILE:-/var/log/zfs-sync-executor.log}"
DRY_RUN="${DRY_RUN:-false}"

# Logging function
log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "$LOG_FILE"
}

# Error handling
error_exit() {
    log "ERROR: $*"
    exit 1
}

# Check required variables
if [ -z "$SYSTEM_ID" ]; then
    error_exit "SYSTEM_ID environment variable is required"
fi

if [ -z "$API_KEY" ]; then
    error_exit "API_KEY environment variable is required"
fi

# Fetch sync instructions from witness service
log "Fetching sync instructions for system $SYSTEM_ID"
INSTRUCTIONS=$(curl -s -f \
    -H "X-API-Key: $API_KEY" \
    "$WITNESS_API_URL/api/v1/sync/instructions/$SYSTEM_ID?include_commands=true") || \
    error_exit "Failed to fetch sync instructions"

# Parse instructions (assuming JSON response)
# This is a simplified example - you may want to use jq for proper JSON parsing
log "Received sync instructions"

# Extract actions from instructions
# Note: This is a template - actual implementation depends on your JSON structure
ACTIONS=$(echo "$INSTRUCTIONS" | jq -r '.actions[]? // empty')

if [ -z "$ACTIONS" ]; then
    log "No sync actions required"
    exit 0
fi

# Execute each sync action
log "Processing sync actions"
EXECUTED=0
FAILED=0

while IFS= read -r action; do
    # Extract sync command from action
    SYNC_COMMAND=$(echo "$action" | jq -r '.sync_command // empty')
    
    if [ -z "$SYNC_COMMAND" ]; then
        log "WARNING: No sync_command in action, skipping"
        continue
    fi
    
    ACTION_TYPE=$(echo "$action" | jq -r '.action_type')
    DATASET=$(echo "$action" | jq -r '.dataset')
    SNAPSHOT=$(echo "$action" | jq -r '.snapshot_name')
    
    log "Executing sync: $ACTION_TYPE for $DATASET@$SNAPSHOT"
    
    if [ "$DRY_RUN" = "true" ]; then
        log "DRY RUN: Would execute: $SYNC_COMMAND"
        EXECUTED=$((EXECUTED + 1))
    else
        # Execute the sync command
        if eval "$SYNC_COMMAND"; then
            log "SUCCESS: Sync completed for $DATASET@$SNAPSHOT"
            EXECUTED=$((EXECUTED + 1))
            
            # Optionally report success back to witness service
            # curl -X POST "$WITNESS_API_URL/api/v1/sync/states" \
            #     -H "X-API-Key: $API_KEY" \
            #     -H "Content-Type: application/json" \
            #     -d "{\"sync_group_id\": \"...\", \"snapshot_id\": \"...\", \"system_id\": \"$SYSTEM_ID\", \"status\": \"completed\"}"
        else
            log "FAILED: Sync failed for $DATASET@$SNAPSHOT"
            FAILED=$((FAILED + 1))
            
            # Optionally report failure back to witness service
            # ERROR_MSG="Sync command execution failed"
            # curl -X POST "$WITNESS_API_URL/api/v1/sync/states" \
            #     -H "X-API-Key: $API_KEY" \
            #     -H "Content-Type: application/json" \
            #     -d "{\"sync_group_id\": \"...\", \"snapshot_id\": \"...\", \"system_id\": \"$SYSTEM_ID\", \"status\": \"failed\", \"error_message\": \"$ERROR_MSG\"}"
        fi
    fi
done <<< "$ACTIONS"

log "Sync execution complete: $EXECUTED succeeded, $FAILED failed"

if [ $FAILED -gt 0 ]; then
    exit 1
fi

exit 0

