#!/bin/bash
#
# ZFS Sync Report Script
#
# This script reports ZFS snapshots to the witness service and retrieves sync instructions.
# Fixed version with proper dataset parsing, timestamp conversion, batch endpoint, and error handling.
#
# Debugging:
#   - Enable verbose mode: DEBUG=1 ./zfs_sync_report.sh or VERBOSE=1 ./zfs_sync_report.sh
#   - Check server logs: docker logs zfs-sync (if using Docker)
#   - Check host logs: ./logs/ directory (if configured)
#   - View container logs: docker logs zfs-sync --tail 100 -f
#
# Configuration
API_URL="{{ zfs_sync_api_url }}/api/v1"
{% set server_config = zfs_sync_server_list | selectattr('name', 'equalto', inventory_hostname) | first %}
API_KEY="{{ server_config.api_key | default('') }}"
SYSTEM_ID="{{ server_config.id | default('') }}"

# Parallel sync configuration
MAX_PARALLEL_SYNCS="${MAX_PARALLEL_SYNCS:-5}"
SYNC_LOG_DIR="${SYNC_LOG_DIR:-/var/log/zfs-sync}"

# Batch chunking configuration (for large snapshot batches)
# Set to 0 to disable chunking and send all snapshots in one request
SNAPSHOT_BATCH_CHUNK_SIZE="${SNAPSHOT_BATCH_CHUNK_SIZE:-1000}"

# Debug/Verbose mode
# Set to 1 to enable verbose curl output and detailed diagnostics
DEBUG="${DEBUG:-0}"
VERBOSE="${VERBOSE:-${DEBUG}}"

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

# Test API connectivity
test_api_connectivity() {
    log_info "Testing API connectivity to ${API_URL}"

    # Try a simple GET request to health endpoint (no auth required)
    local health_url="${API_URL}/health"
    local curl_opts=(-s -w "\n%{http_code}" --max-time 5)

    if [ "${VERBOSE:-0}" = "1" ]; then
        curl_opts+=(-v)
        log_info "Testing connection to: $health_url"
    fi

    local response=$(curl "${curl_opts[@]}" "$health_url" 2>&1) || {
        local exit_code=$?
        log_error "Cannot connect to API server at ${API_URL}"
        log_error "Curl exit code: $exit_code"
        case $exit_code in
            6)  log_error "Could not resolve host. Check DNS or API_URL setting." ;;
            7)  log_error "Failed to connect to host. Check if server is running and reachable." ;;
            28) log_error "Connection timeout. Check network connectivity and firewall settings." ;;
            *)  log_error "Connection failed. Check API_URL: ${API_URL}" ;;
        esac
        log_error ""
        log_error "Troubleshooting:"
        log_error "  1. Verify API server is running: curl ${API_URL}/health"
        log_error "  2. Check API_URL setting: ${API_URL}"
        log_error "  3. Check network connectivity: ping $(echo ${API_URL} | sed -e 's|http://||' -e 's|https://||' -e 's|:.*||')"
        log_error "  4. Check server logs: docker logs zfs-sync (if using Docker)"
        return $exit_code
    }

    local http_code=$(echo "$response" | tail -n1)
    if [ "$http_code" -ge 200 ] && [ "$http_code" -lt 300 ]; then
        log_info "API connectivity test passed"
        return 0
    else
        log_error "API connectivity test failed (HTTP $http_code)"
        return 1
    fi
}

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

    # Add verbose mode if enabled
    if [ "${VERBOSE:-0}" = "1" ]; then
        curl_opts+=(-v)
        log_info "API Request: $method $url"
    fi

    local response
    if [ "$method" = "POST" ] && [ -n "$data" ]; then
        # Use stdin for data to avoid command-line argument length limits
        # This is critical for large payloads (1000+ snapshots)
        response=$(echo "$data" | curl "${curl_opts[@]}" --data-binary @- "$url" 2>&1) || {
            local exit_code=$?
            log_error "API request failed: $method $endpoint"
            log_error "URL: $url"
            log_error "Curl exit code: $exit_code"

            # Provide helpful error messages based on exit code
            case $exit_code in
                6)  log_error "Error: Could not resolve host. Check DNS or API_URL setting." ;;
                7)  log_error "Error: Failed to connect to host. Server may be down or unreachable." ;;
                22) log_error "Error: HTTP error response from server." ;;
                28) log_error "Error: Connection timeout. Server may be overloaded or network slow." ;;
                *)  log_error "Error: Connection failed (exit code: $exit_code)" ;;
            esac

            if [ "${VERBOSE:-0}" = "1" ]; then
                log_error "Full curl output: $response"
            fi

            return $exit_code
        }
    else
        response=$(curl "${curl_opts[@]}" "$url" 2>&1) || {
            local exit_code=$?
            log_error "API request failed: $method $endpoint"
            log_error "URL: $url"
            log_error "Curl exit code: $exit_code"

            # Provide helpful error messages based on exit code
            case $exit_code in
                6)  log_error "Error: Could not resolve host. Check DNS or API_URL setting." ;;
                7)  log_error "Error: Failed to connect to host. Server may be down or unreachable." ;;
                22) log_error "Error: HTTP error response from server." ;;
                28) log_error "Error: Connection timeout. Server may be overloaded or network slow." ;;
                *)  log_error "Error: Connection failed (exit code: $exit_code)" ;;
            esac

            if [ "${VERBOSE:-0}" = "1" ]; then
                log_error "Full curl output: $response"
            fi

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
        log_error "API request failed: $method $endpoint (HTTP $http_code)"
        log_error "URL: $url"
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

    # Test API connectivity before attempting large batch operations
    if ! test_api_connectivity; then
        log_error "Cannot connect to API server. Aborting snapshot report."
        log_error ""
        log_error "Server logs can be found at:"
        log_error "  - Docker: docker logs zfs-sync"
        log_error "  - Host logs: ./logs/ (if configured)"
        log_error "  - Container logs: docker logs zfs-sync --tail 100 -f"
        return 1
    fi

    local snapshots_json=$(get_local_snapshots)
    local snapshot_count=$(echo "$snapshots_json" | jq 'length')

    log_info "Found $snapshot_count snapshots to report"

    if [ "$snapshot_count" -eq 0 ]; then
        log_warning "No snapshots found on this system"
        return 0
    fi

    # Extract and display unique datasets for transparency
    local unique_datasets=$(echo "$snapshots_json" | jq -r '[.[].dataset] | unique | sort | .[]' 2>/dev/null)
    local dataset_count=$(echo "$unique_datasets" | grep -c . || echo "0")
    
    if [ "$dataset_count" -gt 0 ]; then
        log_info "Datasets reported ($dataset_count):"
        echo "$unique_datasets" | while read -r dataset; do
            if [ -n "$dataset" ]; then
                echo "  - $dataset" >&2
            fi
        done
    fi

    # Determine if chunking is needed
    local chunk_size=${SNAPSHOT_BATCH_CHUNK_SIZE:-1000}
    local total_created=0
    local total_failed=0

    if [ "$chunk_size" -gt 0 ] && [ "$snapshot_count" -gt "$chunk_size" ]; then
        # Split into chunks and process sequentially
        log_info "Splitting $snapshot_count snapshots into chunks of $chunk_size"

        local chunk_num=0
        local offset=0

        while [ $offset -lt $snapshot_count ]; do
            chunk_num=$((chunk_num + 1))
            local chunk=$(echo "$snapshots_json" | jq ".[$offset:$((offset + chunk_size))]")
            local chunk_length=$(echo "$chunk" | jq 'length')

            log_info "Processing chunk $chunk_num: $chunk_length snapshots (offset $offset)"

            local response
            local api_exit_code
            response=$(api_request "POST" "/snapshots/batch" "$chunk")
            api_exit_code=$?

            if [ $api_exit_code -eq 0 ]; then
                local created_count=$(echo "$response" | jq 'length' 2>/dev/null || echo "0")
                total_created=$((total_created + created_count))
                log_info "Chunk $chunk_num: Successfully reported $created_count snapshots"
            else
                total_failed=$((total_failed + chunk_length))
                log_error "Chunk $chunk_num: Failed to report $chunk_length snapshots"
                if [ -n "$response" ]; then
                    log_error "Error details: $response"
                fi
                # Continue with next chunk even if this one failed
            fi

            offset=$((offset + chunk_size))
        done

        # Summary
        if [ $total_failed -eq 0 ]; then
            log_info "Successfully reported all $total_created snapshots in $chunk_num chunks"
            return 0
        else
            log_warning "Reported $total_created snapshots successfully, $total_failed failed (in $chunk_num chunks)"
            return 1
        fi
    else
        # Send all snapshots in one request (no chunking needed or disabled)
        local response
        local api_exit_code
        response=$(api_request "POST" "/snapshots/batch" "$snapshots_json")
        api_exit_code=$?

        if [ $api_exit_code -eq 0 ]; then
            # Check if response contains actual data (successful creation)
            local created_count=$(echo "$response" | jq 'length' 2>/dev/null || echo "0")
            if [ "$created_count" -gt 0 ]; then
                log_info "Successfully reported $created_count snapshots (out of $snapshot_count total)"
            else
                log_warning "API returned success but no snapshots were created. Response: $response"
            fi
            return 0
        else
            log_error "Failed to report snapshots"
            # Log the error response if available
            if [ -n "$response" ]; then
                log_error "Error details: $response"
            fi
            return 1
        fi
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
# Command runs locally on source system: zfs send | ssh target "zfs receive"
build_ssh_sync_command() {
    local pool="$1"
    local dataset="$2"
    local ending_snapshot="$3"
    local starting_snapshot="${4:-}"
    local target_ssh_hostname="$5"  # Target system SSH hostname/alias
    local target_pool="${6:-$pool}"
    local target_dataset="${7:-$dataset}"

    # Build full snapshot paths for source (local)
    local full_ending_snapshot
    if [[ "$dataset" == *"/"* ]]; then
        # Dataset already includes pool (e.g., "tank/data")
        full_ending_snapshot="${dataset}@${ending_snapshot}"
    else
        # Dataset is just name, prepend pool
        full_ending_snapshot="${pool}/${dataset}@${ending_snapshot}"
    fi

    # Build ZFS send command (runs locally on source)
    local zfs_send_cmd
    if [ -n "$starting_snapshot" ] && [ "$starting_snapshot" != "null" ]; then
        # Incremental send with compression
        local full_starting_snapshot
        if [[ "$dataset" == *"/"* ]]; then
            full_starting_snapshot="${dataset}@${starting_snapshot}"
        else
            full_starting_snapshot="${pool}/${dataset}@${starting_snapshot}"
        fi
        # Escape snapshot names for shell
        full_starting_snapshot=$(printf '%q' "$full_starting_snapshot")
        full_ending_snapshot_escaped=$(printf '%q' "$full_ending_snapshot")
        # -I flag requires: first snapshot (common/base/older), second snapshot (ending/newer)
        # The starting snapshot should be the common snapshot (older) and the ending snapshot should be the latest (newer)
        # ZFS requires: zfs send -I <base_snapshot> <ending_snapshot>
        # Order: base (older/starting) first, then ending (newer) second
        zfs_send_cmd="zfs send -c -I ${full_starting_snapshot} ${full_ending_snapshot_escaped}"
    else
        # Full send with compression
        full_ending_snapshot_escaped=$(printf '%q' "$full_ending_snapshot")
        zfs_send_cmd="zfs send -c ${full_ending_snapshot_escaped}"
    fi

    # Build target dataset path
    local target_dataset_path
    if [[ "$target_dataset" == *"/"* ]]; then
        target_dataset_path="$target_dataset"
    else
        target_dataset_path="${target_pool}/${target_dataset}"
    fi
    target_dataset_path=$(printf '%q' "$target_dataset_path")

    # Build SSH receive command (runs on target via SSH)
    # -s flag for sparse receive
    local zfs_receive_cmd="zfs receive -s ${target_dataset_path}"
    local ssh_receive_cmd=$(printf 'ssh %q %q' "$target_ssh_hostname" "$zfs_receive_cmd")

    # Combine: zfs send ... | ssh target "zfs receive ..."
    echo "${zfs_send_cmd} | ${ssh_receive_cmd}"
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
    # Use -c (compact) instead of -r (raw) to output JSON objects that can be parsed
    echo "$response" | jq -c '.datasets[]?' | while IFS= read -r dataset_instruction; do
        # Extract fields from dataset instruction
        local pool=$(echo "$dataset_instruction" | jq -r '.pool // ""')
        local dataset=$(echo "$dataset_instruction" | jq -r '.dataset // ""')
        local target_pool=$(echo "$dataset_instruction" | jq -r '.target_pool // .pool // ""')
        local target_dataset=$(echo "$dataset_instruction" | jq -r '.target_dataset // .dataset // ""')
        local starting_snapshot=$(echo "$dataset_instruction" | jq -r '.starting_snapshot // ""')
        local ending_snapshot=$(echo "$dataset_instruction" | jq -r '.ending_snapshot // ""')
        local target_ssh_hostname=$(echo "$dataset_instruction" | jq -r '.target_ssh_hostname // ""')
        local sync_group_id=$(echo "$dataset_instruction" | jq -r '.sync_group_id // ""')

        # Skip if required fields are missing
        if [ -z "$pool" ] || [ -z "$dataset" ] || [ -z "$ending_snapshot" ] || [ -z "$target_ssh_hostname" ]; then
            log_warning "Skipping incomplete dataset instruction: missing required fields"
            continue
        fi

        # Build the SSH sync command
        # Command runs locally on this system (source) and pipes to target via SSH
        local sync_command=$(build_ssh_sync_command \
            "$pool" \
            "$dataset" \
            "$ending_snapshot" \
            "$starting_snapshot" \
            "$target_ssh_hostname" \
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
            echo "Source: $(hostname) (local)"
            echo "Target: ${target_ssh_hostname}:${target_pool}/${target_dataset}"
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
