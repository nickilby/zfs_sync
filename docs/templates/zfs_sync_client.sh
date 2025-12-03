#!/bin/bash
#
# ZFS Sync Client Script
#
# This script runs on target ZFS systems to:
# 1. Report current snapshot state to the witness service
# 2. Fetch sync instructions from the witness service
# 3. Execute sync commands to synchronize snapshots
# 4. Update heartbeat status
#
# Designed for cron execution (e.g., every 15-30 minutes)
#
# SETUP INSTRUCTIONS:
# ===================
#
# 1. Copy this script to your ZFS system:
#    sudo cp zfs_sync_client.sh /usr/local/bin/
#    sudo chmod +x /usr/local/bin/zfs_sync_client.sh
#
# 2. Register your system with the witness service to get SYSTEM_ID and API_KEY:
#    curl -X POST "http://witness-service:8000/api/v1/systems/register" \
#      -H "Content-Type: application/json" \
#      -d '{"hostname": "your-system-hostname", "platform": "linux"}'
#
# 3. Create a configuration file /etc/zfs-sync-client.conf (optional):
#    export WITNESS_API_URL="http://witness-service:8000"
#    export SYSTEM_ID="your-system-id-from-registration"
#    export API_KEY="your-api-key-from-registration"
#    export LOG_FILE="/var/log/zfs-sync-client.log"
#    export DRY_RUN="false"
#
# 4. Source the config in cron or create a wrapper script:
#    #!/bin/bash
#    source /etc/zfs-sync-client.conf
#    /usr/local/bin/zfs_sync_client.sh
#
# 5. Add to crontab (runs every 30 minutes):
#    */30 * * * * source /etc/zfs-sync-client.conf && /usr/local/bin/zfs_sync_client.sh >> /var/log/zfs-sync-client.log 2>&1
#
# 6. For systemd timer (alternative to cron), create:
#    /etc/systemd/system/zfs-sync-client.service
#    /etc/systemd/system/zfs-sync-client.timer
#
# REQUIREMENTS:
# - bash 4.0+
# - zfs command (ZFS utilities)
# - ssh command (OpenSSH client)
# - curl command
# - jq command (JSON parser)
#
# Usage:
#   ./zfs_sync_client.sh
#   or via cron (see above)

set -euo pipefail

# ============================================================================
# CONFIGURATION
# ============================================================================

# Witness service API URL
WITNESS_API_URL="${WITNESS_API_URL:-http://localhost:8000}"

# System identification (obtained during registration)
SYSTEM_ID="${SYSTEM_ID:-}"
API_KEY="${API_KEY:-}"

# Optional: Sync group ID (if not specified, processes all sync groups for this system)
SYNC_GROUP_ID="${SYNC_GROUP_ID:-}"

# Logging
LOG_FILE="${LOG_FILE:-/var/log/zfs-sync-client.log}"
LOG_LEVEL="${LOG_LEVEL:-INFO}"  # DEBUG, INFO, WARNING, ERROR

# Execution options
DRY_RUN="${DRY_RUN:-false}"  # Set to "true" to preview commands without executing
MAX_CONCURRENT_SYNCS="${MAX_CONCURRENT_SYNCS:-1}"  # Number of syncs to run in parallel
TIMEOUT_SECONDS="${TIMEOUT_SECONDS:-3600}"  # Timeout for sync operations (1 hour default)

# ZFS command paths (adjust if ZFS is not in PATH)
ZFS_CMD="${ZFS_CMD:-zfs}"
SSH_CMD="${SSH_CMD:-ssh}"

# ============================================================================
# FUNCTIONS
# ============================================================================

# Logging function
log() {
    local level="$1"
    shift
    local message="$*"
    local timestamp=$(date '+%Y-%m-%d %H:%M:%S')

    # Check log level
    case "$LOG_LEVEL" in
        DEBUG)
            echo "[$timestamp] [$level] $message" | tee -a "$LOG_FILE"
            ;;
        INFO)
            if [[ "$level" != "DEBUG" ]]; then
                echo "[$timestamp] [$level] $message" | tee -a "$LOG_FILE"
            fi
            ;;
        WARNING)
            if [[ "$level" != "DEBUG" && "$level" != "INFO" ]]; then
                echo "[$timestamp] [$level] $message" | tee -a "$LOG_FILE"
            fi
            ;;
        ERROR)
            if [[ "$level" == "ERROR" ]]; then
                echo "[$timestamp] [$level] $message" | tee -a "$LOG_FILE"
            fi
            ;;
    esac
}

log_info() {
    log "INFO" "$@"
}

log_debug() {
    log "DEBUG" "$@"
}

log_warning() {
    log "WARNING" "$@"
}

log_error() {
    log "ERROR" "$@"
}

# Error handling
error_exit() {
    log_error "$@"
    exit 1
}

# Check if required commands are available
check_dependencies() {
    local missing=()

    if ! command -v "$ZFS_CMD" &> /dev/null; then
        missing+=("zfs")
    fi

    if ! command -v "$SSH_CMD" &> /dev/null; then
        missing+=("ssh")
    fi

    if ! command -v curl &> /dev/null; then
        missing+=("curl")
    fi

    if ! command -v jq &> /dev/null; then
        missing+=("jq")
    fi

    if [ ${#missing[@]} -gt 0 ]; then
        error_exit "Missing required commands: ${missing[*]}"
    fi
}

# Check required configuration
check_config() {
    if [ -z "$SYSTEM_ID" ]; then
        error_exit "SYSTEM_ID environment variable is required"
    fi

    if [ -z "$API_KEY" ]; then
        error_exit "API_KEY environment variable is required"
    fi

    if [ -z "$WITNESS_API_URL" ]; then
        error_exit "WITNESS_API_URL environment variable is required"
    fi
}

# Make API request with error handling
api_request() {
    local method="$1"
    local endpoint="$2"
    local data="${3:-}"
    local response

    local url="${WITNESS_API_URL}${endpoint}"
    local curl_opts=(
        -s
        -f
        -w "\n%{http_code}"
        -H "X-API-Key: $API_KEY"
        -H "Content-Type: application/json"
    )

    if [ "$method" = "GET" ]; then
        response=$(curl "${curl_opts[@]}" "$url" 2>&1) || {
            local exit_code=$?
            log_error "API request failed: $endpoint (exit code: $exit_code)"
            return $exit_code
        }
    elif [ "$method" = "POST" ]; then
        if [ -n "$data" ]; then
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
    else
        error_exit "Unsupported HTTP method: $method"
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

# Update heartbeat
update_heartbeat() {
    log_debug "Updating heartbeat for system $SYSTEM_ID"

    if api_request "POST" "/api/v1/systems/$SYSTEM_ID/heartbeat" > /dev/null; then
        log_debug "Heartbeat updated successfully"
        return 0
    else
        log_warning "Failed to update heartbeat"
        return 1
    fi
}

# Get all ZFS snapshots on this system
get_local_snapshots() {
    log_debug "Collecting local ZFS snapshots"

    # Get all snapshots with raw numeric values (-p flag)
    # Format: pool/dataset@snapshot_name
    local snapshots_json="[]"

    # Use zfs list to get all snapshots with raw numeric values
    # -p: print raw numeric values (creation time as Unix timestamp, sizes in bytes)
    # -H: scripted mode (no headers)
    # -o: output fields: name,creation,used,referenced
    while IFS=$'\t' read -r name creation used referenced; do
        # Parse snapshot name (pool/dataset@snapshot)
        if [[ "$name" =~ ^([^@]+)@(.+)$ ]]; then
            local full_path="${BASH_REMATCH[1]}"
            local snapshot_name="${BASH_REMATCH[2]}"

            # Split pool/dataset
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
    done < <($ZFS_CMD list -t snapshot -H -p -o name,creation,used,referenced 2>/dev/null || true)

    echo "$snapshots_json"
}

# Report snapshots to witness service
report_snapshots() {
    log_info "Reporting snapshot state to witness service"

    local snapshots_json=$(get_local_snapshots)
    local snapshot_count=$(echo "$snapshots_json" | jq 'length')

    log_info "Found $snapshot_count snapshots to report"

    if [ "$snapshot_count" -eq 0 ]; then
        log_warning "No snapshots found on this system"
        return 0
    fi

    # Prepare batch request (API expects array directly, not wrapped in object)
    if api_request "POST" "/api/v1/snapshots/batch" "$snapshots_json" > /dev/null; then
        log_info "Successfully reported $snapshot_count snapshots"
        return 0
    else
        log_error "Failed to report snapshots"
        return 1
    fi
}

# Get sync instructions from witness service
get_sync_instructions() {
    log_info "Fetching sync instructions from witness service"

    local endpoint="/api/v1/sync/instructions/$SYSTEM_ID?include_commands=true"
    if [ -n "$SYNC_GROUP_ID" ]; then
        endpoint="${endpoint}&sync_group_id=$SYNC_GROUP_ID"
    fi

    local response=$(api_request "GET" "$endpoint")

    if [ $? -eq 0 ] && [ -n "$response" ]; then
        echo "$response"
        return 0
    else
        log_error "Failed to get sync instructions"
        return 1
    fi
}

# Execute a sync command
execute_sync_command() {
    local action="$1"
    local action_type=$(echo "$action" | jq -r '.action_type')
    local pool=$(echo "$action" | jq -r '.pool')
    local dataset=$(echo "$action" | jq -r '.dataset')
    local snapshot_name=$(echo "$action" | jq -r '.snapshot_name')
    local sync_command=$(echo "$action" | jq -r '.sync_command // empty')
    local snapshot_id=$(echo "$action" | jq -r '.snapshot_id // empty')

    log_info "Executing sync: $action_type for $pool/$dataset@$snapshot_name"

    if [ -z "$sync_command" ]; then
        log_warning "No sync_command provided for action, skipping"
        return 1
    fi

    if [ "$DRY_RUN" = "true" ]; then
        log_info "DRY RUN: Would execute: $sync_command"
        return 0
    fi

    # Execute the sync command with timeout
    log_debug "Executing command: $sync_command"

    local start_time=$(date +%s)
    local exit_code=0
    local output=""

    # Use timeout if available
    if command -v timeout &> /dev/null; then
        output=$(timeout "$TIMEOUT_SECONDS" bash -c "$sync_command" 2>&1) || exit_code=$?
    else
        output=$(bash -c "$sync_command" 2>&1) || exit_code=$?
    fi

    local end_time=$(date +%s)
    local duration=$((end_time - start_time))

    if [ $exit_code -eq 0 ]; then
        log_info "SUCCESS: Sync completed for $pool/$dataset@$snapshot_name (duration: ${duration}s)"
        log_debug "Command output: $output"
        return 0
    else
        log_error "FAILED: Sync failed for $pool/$dataset@$snapshot_name (exit code: $exit_code, duration: ${duration}s)"
        log_error "Command output: $output"
        return 1
    fi
}

# Process sync instructions
process_sync_instructions() {
    local instructions_json="$1"
    local action_count=$(echo "$instructions_json" | jq -r '.action_count // 0')

    if [ "$action_count" -eq 0 ]; then
        log_info "No sync actions required"
        return 0
    fi

    log_info "Processing $action_count sync actions"

    local executed=0
    local failed=0
    local actions=$(echo "$instructions_json" | jq -c '.actions[]? // empty')

    # Process actions sequentially (can be modified for parallel execution)
    while IFS= read -r action; do
        if [ -z "$action" ]; then
            continue
        fi

        if execute_sync_command "$action"; then
            executed=$((executed + 1))
        else
            failed=$((failed + 1))
        fi
    done <<< "$actions"

    log_info "Sync execution complete: $executed succeeded, $failed failed"

    if [ $failed -gt 0 ]; then
        return 1
    fi

    return 0
}

# Main execution function
main() {
    log_info "=========================================="
    log_info "ZFS Sync Client Script Started"
    log_info "System ID: $SYSTEM_ID"
    log_info "Witness API: $WITNESS_API_URL"
    log_info "Dry Run: $DRY_RUN"
    log_info "=========================================="

    # Pre-flight checks
    check_dependencies
    check_config

    # Update heartbeat
    update_heartbeat

    # Report current snapshot state
    if ! report_snapshots; then
        log_warning "Failed to report snapshots, continuing anyway"
    fi

    # Get sync instructions
    local instructions=$(get_sync_instructions)
    if [ $? -ne 0 ] || [ -z "$instructions" ]; then
        log_error "Failed to get sync instructions"
        exit 1
    fi

    # Process sync instructions
    if ! process_sync_instructions "$instructions"; then
        log_warning "Some sync operations failed"
        exit 1
    fi

    log_info "ZFS Sync Client Script Completed Successfully"
    return 0
}

# ============================================================================
# SCRIPT EXECUTION
# ============================================================================

# Trap errors
trap 'log_error "Script failed at line $LINENO"' ERR

# Run main function
main "$@"
