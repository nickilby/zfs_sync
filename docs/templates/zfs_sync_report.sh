#!/bin/bash
#
# ZFS Sync Report Script
# 
# This script reports ZFS snapshots to the witness service and retrieves sync instructions.
# Fixed version with proper dataset parsing, timestamp conversion, batch endpoint, and error handling.
#
# Configuration
API_URL="${API_URL:-http://localhost8000/api/v1}"
API_KEY="${API_KEY:-}"
SYSTEM_ID="${SYSTEM_ID:-}"

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

# Get sync instructions
get_sync_instructions() {
    log_info "Fetching sync instructions from witness service"
    
    local response=$(api_request "GET" "/sync/instructions/$SYSTEM_ID?include_commands=true")
    
    if [ $? -eq 0 ] && [ -n "$response" ]; then
        log_info "Received sync instructions"
        
        # Process sync instructions (example - you would implement actual ZFS sync here)
        # The instructions include snapshot_id which can be used to update sync state
        echo "$response" | jq -r '.actions[]? | "\(.snapshot_name) from \(.source_system_id) to \(.target_system_id) (snapshot_id: \(.snapshot_id))"' || true
        
        return 0
    else
        log_error "Failed to get sync instructions"
        return 1
    fi
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

