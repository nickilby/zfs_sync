#!/bin/bash
#
# ZFS Sync Report Script
# 
# This script reports ZFS snapshots to the witness service and retrieves sync instructions.
# Fixed version with proper dataset parsing, timestamp conversion, batch endpoint, and error handling.
#
# Configuration
API_URL="{{ zfs_sync_api_url }}/api/v1"
{% set server_config = zfs_sync_server_list | selectattr('name', 'equalto', inventory_hostname) | first %}
API_KEY="{{ server_config.api_key | default('') }}"
SYSTEM_ID="{{ server_config.id | default('') }}"

# Parallel sync configuration
MAX_PARALLEL_SYNCS="${MAX_PARALLEL_SYNCS:-5}"
SYNC_LOG_DIR="${SYNC_LOG_DIR:-/var/log/zfs-sync}"

# Error handling
set -euo pipefail

# Colors for output (optional)
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Logging functions
log_info() {
    echo -e "${GREEN}[INFO]${NC} $*" >&2
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $*" >&2
}

log_warning() {
    echo -e "${YELLOW}[WARN]${NC} $*" >&2
}

# Ensure sync log directory exists
ensure_sync_log_dir() {
    if [ ! -d "$SYNC_LOG_DIR" ]; then
        log_info "Creating sync log directory: $SYNC_LOG_DIR"
        mkdir -p "$SYNC_LOG_DIR" || {
            log_error "Failed to create sync log directory: $SYNC_LOG_DIR"
            return 1
        }
    fi
    # Ensure directory is writable
    if [ ! -w "$SYNC_LOG_DIR" ]; then
        log_error "Sync log directory is not writable: $SYNC_LOG_DIR"
        return 1
    fi
    return 0
}

# Check required variables
if [ -z "$API_KEY" ]; then
    log_error "API_KEY environment variable is required"
    exit 1
fi

if [ -z "$SYSTEM_ID" ]; then
    log_error "SYSTEM_ID environment variable is required"
    exit 1
fi

# API request helper with error handling
api_request() {
    local method="$1"
    local endpoint="$2"
    local data="${3:-}"
    local url="${API_URL}${endpoint}"
    
    local curl_opts=(
        -s
        -w "\n%{http_code}"
        -X "$method"
        -H "X-API-Key: $API_KEY"
        -H "Content-Type: application/json"
    )
    
    local response
    if [ "$method" = "POST" ] && [ -n "$data" ]; then
        response=$(curl "${curl_opts[@]}" -d "$data" "$url" 2>&1) || {
            local exit_code=$?
            log_error "API request failed: $endpoint (exit code: $exit_code)"
            return $exit_code
        }
    else
        response=$(curl "${curl_opts[@]}" "$url" 2>&1) || {
            local exit_code=$?
            log_error "API request failed: $endpoint (exit code: $exit_code)"
            return $exit_code
        }
    fi
    
    # Extract HTTP status code (last line)
    local http_code=$(echo "$response" | tail -n1)
    local body=$(echo "$response" | sed '$d')
    
    if [ "$http_code" -ge 200 ] && [ "$http_code" -lt 300 ]; then
        echo "$body"
        return 0
    else
        log_error "API request failed: $endpoint (HTTP $http_code)"
        log_error "Response: $body"
        return 1
    fi
}

# Get all ZFS snapshots on this system
get_local_snapshots() {
    log_info "Collecting local ZFS snapshots"
    
    local snapshots_json="[]"
    
    # Use zfs list with -p flag to get raw numeric values
    # -p: print raw numeric values (creation time as Unix timestamp, sizes in bytes)
    # -H: scripted mode (no headers)
    # -o: output fields: name,creation,used,referenced
    while IFS=$'\t' read -r name creation used referenced; do
        # Parse snapshot name (pool/dataset/subdataset@snapshot)
        if [[ "$name" =~ ^([^@]+)@(.+)$ ]]; then
            local full_path="${BASH_REMATCH[1]}"
            local snapshot_name="${BASH_REMATCH[2]}"
            
            # Split pool/dataset correctly
            # Handle nested datasets like pool/dataset/subdataset
            if [[ "$full_path" =~ ^([^/]+)/(.+)$ ]]; then
                local pool="${BASH_REMATCH[1]}"
                local dataset="${BASH_REMATCH[2]}"
            else
                # No dataset, just pool
                local pool="$full_path"
                local dataset=""
            fi
            
            # Convert creation time (Unix timestamp) to ISO format
            local timestamp
            if command -v date &> /dev/null; then
                # Try GNU date first (Linux)
                timestamp=$(date -d "@$creation" -u +"%Y-%m-%dT%H:%M:%SZ" 2>/dev/null || \
                           # Fallback to BSD date (macOS/FreeBSD)
                           date -r "$creation" -u +"%Y-%m-%dT%H:%M:%SZ" 2>/dev/null || \
                           # Last resort: current time
                           date -u +"%Y-%m-%dT%H:%M:%SZ")
            else
                timestamp=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
            fi
            
            # Sizes are already in bytes from -p flag
            local used_bytes="${used:-0}"
            local referenced_bytes="${referenced:-0}"
            
            # Build JSON object (must include system_id for batch endpoint)
            local snapshot_json=$(jq -n \
                --arg name "$snapshot_name" \
                --arg pool "$pool" \
                --arg dataset "$dataset" \
                --arg timestamp "$timestamp" \
                --arg system_id "$SYSTEM_ID" \
                --argjson used "$used_bytes" \
                --argjson referenced "$referenced_bytes" \
                '{
                    name: $name,
                    pool: $pool,
                    dataset: $dataset,
                    timestamp: $timestamp,
                    size: $used,
                    referenced: $referenced,
                    system_id: $system_id
                }')
            
            snapshots_json=$(echo "$snapshots_json" | jq ". += [$snapshot_json]")
        fi
    done < <(zfs list -t snapshot -H -p -o name,creation,used,referenced 2>/dev/null || true)
    
    echo "$snapshots_json"
}

# Report snapshots to witness service using batch endpoint
report_snapshots() {
    log_info "Reporting snapshot state to witness service"
    
    local snapshots_json=$(get_local_snapshots)
    local snapshot_count=$(echo "$snapshots_json" | jq 'length')
    
    log_info "Found $snapshot_count snapshots to report"
    
    if [ "$snapshot_count" -eq 0 ]; then
        log_warning "No snapshots found on this system"
        return 0
    fi
    
    # Use batch endpoint to report all snapshots at once
    local response=$(api_request "POST" "/snapshots/batch" "$snapshots_json")
    
    if [ $? -eq 0 ]; then
        log_info "Successfully reported $snapshot_count snapshots"
        return 0
    else
        log_error "Failed to report snapshots"
        return 1
    fi
}

# Send heartbeat
send_heartbeat() {
    log_info "Sending heartbeat"
    
    if api_request "POST" "/systems/$SYSTEM_ID/heartbeat" > /dev/null; then
        log_info "Heartbeat sent successfully"
        return 0
    else
        log_warning "Failed to send heartbeat"
        return 1
    fi
}

# Build SSH command from sync instruction
build_ssh_sync_command() {
    local pool="$1"
    local dataset="$2"
    local ending_snapshot="$3"
    local starting_snapshot="${4:-}"
    local ssh_hostname="$5"
    local ssh_user="${6:-}"
    local ssh_port="${7:-22}"
    local target_pool="${8:-$pool}"
    local target_dataset="${9:-$dataset}"
    
    # Build full snapshot paths
    local full_ending_snapshot
    if [[ "$dataset" == *"/"* ]]; then
        # Dataset already includes pool (e.g., "tank/data")
        full_ending_snapshot="${dataset}@${ending_snapshot}"
    else
        # Dataset is just name, prepend pool
        full_ending_snapshot="${pool}/${dataset}@${ending_snapshot}"
    fi
    
    # Build SSH command parts
    local ssh_cmd="ssh"
    if [ "$ssh_port" != "22" ] && [ -n "$ssh_port" ]; then
        ssh_cmd="${ssh_cmd} -p ${ssh_port}"
    fi
    
    local ssh_target
    if [ -n "$ssh_user" ]; then
        ssh_target="${ssh_user}@${ssh_hostname}"
    else
        ssh_target="${ssh_hostname}"
    fi
    
    # Build ZFS send command
    local zfs_send_cmd
    if [ -n "$starting_snapshot" ] && [ "$starting_snapshot" != "null" ]; then
        # Incremental send
        local full_starting_snapshot
        if [[ "$dataset" == *"/"* ]]; then
            full_starting_snapshot="${dataset}@${starting_snapshot}"
        else
            full_starting_snapshot="${pool}/${dataset}@${starting_snapshot}"
        fi
        # Escape snapshot names for shell
        full_starting_snapshot=$(printf '%q' "$full_starting_snapshot")
        full_ending_snapshot_escaped=$(printf '%q' "$full_ending_snapshot")
        zfs_send_cmd="zfs send -I ${full_starting_snapshot} ${full_ending_snapshot_escaped}"
    else
        # Full send
        full_ending_snapshot_escaped=$(printf '%q' "$full_ending_snapshot")
        zfs_send_cmd="zfs send ${full_ending_snapshot_escaped}"
    fi
    
    # Build ZFS receive command
    local target_dataset_path
    if [[ "$target_dataset" == *"/"* ]]; then
        target_dataset_path="$target_dataset"
    else
        target_dataset_path="${target_pool}/${target_dataset}"
    fi
    target_dataset_path=$(printf '%q' "$target_dataset_path")
    local zfs_receive_cmd="zfs receive -F ${target_dataset_path}"
    
    # Combine: ssh ... 'zfs send ...' | zfs receive ...
    echo "${ssh_cmd} ${ssh_target} '${zfs_send_cmd}' | ${zfs_receive_cmd}"
}

# Get sync instructions and process them
get_sync_instructions() {
    log_info "Fetching sync instructions from witness service"
    
    local response=$(api_request "GET" "/sync/instructions/$SYSTEM_ID")
    
    if [ $? -ne 0 ] || [ -z "$response" ]; then
        log_error "Failed to get sync instructions"
        return 1
    fi
    
    log_info "Received sync instructions"
    
    # Ensure sync log directory exists
    if ! ensure_sync_log_dir; then
        log_error "Cannot proceed without sync log directory"
        return 1
    fi
    
    # Check if we have datasets to sync
    local dataset_count=$(echo "$response" | jq -r '.dataset_count // 0')
    
    if [ "$dataset_count" -eq 0 ]; then
        log_info "No datasets require syncing"
        return 0
    fi
    
    log_info "Found $dataset_count dataset(s) requiring sync"
    log_info "Maximum parallel syncs: $MAX_PARALLEL_SYNCS"
    
    # Process each dataset instruction with parallel execution
    echo "$response" | jq -r '.datasets[]?' | while IFS= read -r dataset_instruction; do
        # Extract fields from dataset instruction
        local pool=$(echo "$dataset_instruction" | jq -r '.pool // ""')
        local dataset=$(echo "$dataset_instruction" | jq -r '.dataset // ""')
        local target_pool=$(echo "$dataset_instruction" | jq -r '.target_pool // .pool // ""')
        local target_dataset=$(echo "$dataset_instruction" | jq -r '.target_dataset // .dataset // ""')
        local starting_snapshot=$(echo "$dataset_instruction" | jq -r '.starting_snapshot // ""')
        local ending_snapshot=$(echo "$dataset_instruction" | jq -r '.ending_snapshot // ""')
        local ssh_hostname=$(echo "$dataset_instruction" | jq -r '.source_ssh_hostname // ""')
        local sync_group_id=$(echo "$dataset_instruction" | jq -r '.sync_group_id // ""')
        
        # Skip if required fields are missing
        if [ -z "$pool" ] || [ -z "$dataset" ] || [ -z "$ending_snapshot" ] || [ -z "$ssh_hostname" ]; then
            log_warning "Skipping incomplete dataset instruction: missing required fields"
            continue
        fi
        
        # Get SSH details from source system (if not in instruction, we'd need to fetch from API)
        # For now, assume they're in the instruction or use defaults
        local ssh_user=$(echo "$dataset_instruction" | jq -r '.source_ssh_user // ""')
        local ssh_port=$(echo "$dataset_instruction" | jq -r '.source_ssh_port // 22')
        
        # Build the SSH sync command
        local sync_command=$(build_ssh_sync_command \
            "$pool" \
            "$dataset" \
            "$ending_snapshot" \
            "$starting_snapshot" \
            "$ssh_hostname" \
            "$ssh_user" \
            "$ssh_port" \
            "$target_pool" \
            "$target_dataset" \
        )
        
        # Wait for available slot in job pool
        while [ $(jobs -r | wc -l) -ge "$MAX_PARALLEL_SYNCS" ]; do
            sleep 0.1
        done
        
        # Create log file name with timestamp
        local timestamp=$(date +%Y%m%d_%H%M%S)
        local safe_pool=$(echo "$pool" | tr '/' '_')
        local safe_dataset=$(echo "$dataset" | tr '/' '_')
        local safe_snapshot=$(echo "$ending_snapshot" | tr '/' '_')
        local log_file="${SYNC_LOG_DIR}/sync-${safe_pool}-${safe_dataset}-${safe_snapshot}-${timestamp}.log"
        
        # Launch sync command in background (fire-and-forget)
        log_info "Launching sync for ${pool}/${dataset}@${ending_snapshot} (PID will be logged)"
        (
            echo "=== ZFS Sync Operation Started ==="
            echo "Pool: $pool"
            echo "Dataset: $dataset"
            echo "Snapshot: $ending_snapshot"
            echo "Starting Snapshot: ${starting_snapshot:-none (full sync)}"
            echo "Target: ${target_pool}/${target_dataset}"
            echo "Source: ${ssh_user:+${ssh_user}@}${ssh_hostname}:${ssh_port}"
            echo "Started: $(date)"
            echo "Command: $sync_command"
            echo "=================================="
            echo ""
            
            # Execute the sync command
            if eval "$sync_command"; then
                echo ""
                echo "=== Sync Completed Successfully ==="
                echo "Completed: $(date)"
            else
                local exit_code=$?
                echo ""
                echo "=== Sync Failed ==="
                echo "Exit code: $exit_code"
                echo "Failed at: $(date)"
                exit $exit_code
            fi
        ) > "$log_file" 2>&1 &
        
        local sync_pid=$!
        
        # Disown the process so it's fully detached from parent
        disown $sync_pid
        
        # Log the launch information
        log_info "Sync launched for ${pool}/${dataset}@${ending_snapshot} (PID: $sync_pid, Log: $log_file)"
    done
    
    # Wait a moment for all jobs to start
    sleep 0.5
    
    # Log summary
    local running_jobs=$(jobs -r | wc -l)
    log_info "Sync operations launched. $running_jobs currently running in background (max: $MAX_PARALLEL_SYNCS)."
    log_info "Sync operations are running independently. Check logs in $SYNC_LOG_DIR for progress."
    
    return 0
}

# Main execution
main() {
    log_info "Starting ZFS sync report"
    
    # Report snapshots
    if ! report_snapshots; then
        log_error "Failed to report snapshots"
        exit 1
    fi
    
    # Send heartbeat
    send_heartbeat
    
    # Get sync instructions
    get_sync_instructions
    
    log_info "ZFS sync report completed"
}

# Run main function
main

