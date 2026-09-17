#!/bin/bash
#
# ZFS Sync Executor
#
# Fetches sync instructions from the witness service, performs each one, and
# reports the outcome back.
#
# Run this on the SOURCE system. The witness only ever hands a system the pairs
# it can actually execute -- commands send from the source's own pool -- so on a
# hub-and-spoke fleet this runs on the hub and receives one instruction per
# lagging target.
#
# Two things this script deliberately does not do:
#
#   * It does not eval the server's rendered command. The response carries the
#     command as text for display and dry runs, but execution rebuilds it from
#     the structured fields and runs it as an argument vector, so nothing the
#     API returns can be interpreted as shell syntax.
#   * It does not guess at the response shape. Every field it reads is asserted
#     by tests/integration/test_api/test_client_contract.py, so drift fails CI
#     rather than silently producing a script that syncs nothing.
#
# Environment:
#   WITNESS_API_URL  Base URL of the witness service (default http://localhost:8000)
#   SYSTEM_ID        This system's registered UUID (required)
#   API_KEY          This system's API key (required)
#   SYNC_GROUP_ID    Restrict to one sync group (optional)
#   DRY_RUN          "true" to print what would run without running it
#   LOG_FILE         Where to append logs (default /var/log/zfs-sync-executor.log)

set -euo pipefail

WITNESS_API_URL="${WITNESS_API_URL:-http://localhost:8000}"
SYSTEM_ID="${SYSTEM_ID:-}"
API_KEY="${API_KEY:-}"
SYNC_GROUP_ID="${SYNC_GROUP_ID:-}"
LOG_FILE="${LOG_FILE:-/var/log/zfs-sync-executor.log}"
DRY_RUN="${DRY_RUN:-false}"

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "$LOG_FILE"
}

error_exit() {
    log "ERROR: $*"
    exit 1
}

command -v jq >/dev/null 2>&1 || error_exit "jq is required but not installed"
command -v zfs >/dev/null 2>&1 || error_exit "zfs is required but not installed"
[ -n "$SYSTEM_ID" ] || error_exit "SYSTEM_ID environment variable is required"
[ -n "$API_KEY" ] || error_exit "API_KEY environment variable is required"

# ---------------------------------------------------------------------------
# Fetch instructions
# ---------------------------------------------------------------------------

INSTRUCTIONS_URL="${WITNESS_API_URL}/api/v1/sync/instructions/${SYSTEM_ID}"
if [ -n "$SYNC_GROUP_ID" ]; then
    INSTRUCTIONS_URL="${INSTRUCTIONS_URL}?sync_group_id=${SYNC_GROUP_ID}"
fi

log "Fetching sync instructions for system $SYSTEM_ID"

HTTP_BODY=$(mktemp)
trap 'rm -f "$HTTP_BODY"' EXIT

HTTP_CODE=$(curl -sS -o "$HTTP_BODY" -w '%{http_code}' \
    -H "X-API-Key: $API_KEY" \
    "$INSTRUCTIONS_URL") || error_exit "Could not reach the witness service at $WITNESS_API_URL"

if [ "$HTTP_CODE" != "200" ]; then
    DETAIL=$(jq -r '.detail // .error.message // "no detail"' < "$HTTP_BODY" 2>/dev/null || echo "unparseable response")
    case "$HTTP_CODE" in
        401) error_exit "Authentication failed (401): $DETAIL. Check API_KEY." ;;
        403) error_exit "Forbidden (403): $DETAIL. Check SYSTEM_ID matches this key." ;;
        404) error_exit "Not found (404): $DETAIL. Check SYSTEM_ID and SYNC_GROUP_ID." ;;
        *)   error_exit "Request failed (HTTP $HTTP_CODE): $DETAIL" ;;
    esac
fi

INSTRUCTIONS=$(cat "$HTTP_BODY")
DATASET_COUNT=$(echo "$INSTRUCTIONS" | jq -r '.dataset_count // 0')

# ---------------------------------------------------------------------------
# Report why nothing is happening, when nothing is happening
# ---------------------------------------------------------------------------

DECLINED_COUNT=$(echo "$INSTRUCTIONS" | jq -r '.declined | length')
if [ "$DECLINED_COUNT" -gt 0 ]; then
    log "$DECLINED_COUNT pair(s) evaluated and not scheduled:"
    echo "$INSTRUCTIONS" | jq -r \
        '.declined[] | "  \(.dataset) -> \(.target_hostname // .target_system_id): \(.reason // "no reason given")"' \
        | while IFS= read -r line; do log "$line"; done
fi

if [ "$DATASET_COUNT" -eq 0 ]; then
    log "No datasets require syncing"
    exit 0
fi

log "$DATASET_COUNT dataset(s) require syncing"

# ---------------------------------------------------------------------------
# Execute
# ---------------------------------------------------------------------------

report_result() {
    # report_result <sync_group_id> <dataset> <target_system_id> <status>
    #               <start> <end> <duration> <error>
    local payload
    payload=$(jq -n \
        --arg group "$1" --arg dataset "$2" \
        --arg source "$SYSTEM_ID" --arg target "$3" \
        --arg status "$4" --arg start "$5" --arg end "$6" \
        --argjson duration "$7" --arg err "$8" \
        '{
            sync_group_id: $group,
            dataset: $dataset,
            source_system_id: $source,
            target_system_id: $target,
            status: $status,
            starting_snapshot: (if $start == "" then null else $start end),
            ending_snapshot: (if $end == "" then null else $end end),
            duration_seconds: $duration,
            error_message: (if $err == "" then null else $err end)
        }')

    curl -sS -o /dev/null \
        -X POST "${WITNESS_API_URL}/api/v1/sync/results" \
        -H "X-API-Key: $API_KEY" \
        -H "Content-Type: application/json" \
        -d "$payload" \
        || log "WARNING: could not report the outcome to the witness"
}

EXECUTED=0
FAILED=0

# Read one compact JSON object per line so the loop never has to parse shell
# words out of the payload.
while IFS= read -r instruction; do
    [ -n "$instruction" ] || continue

    field() { echo "$instruction" | jq -r "$1"; }

    DATASET=$(field '.dataset')
    POOL=$(field '.pool')
    TARGET_POOL=$(field '.target_pool')
    TARGET_DATASET=$(field '.target_dataset')
    START=$(field '.starting_snapshot // ""')
    END=$(field '.ending_snapshot')
    TARGET_HOST=$(field '.target_ssh_hostname')
    TARGET_USER=$(field '.target_ssh_user // ""')
    TARGET_PORT=$(field '.target_ssh_port // 22')
    REQUIRES_ROLLBACK=$(field '.requires_rollback // false')
    GROUP_ID=$(field '.sync_group_id')
    TARGET_SYSTEM_ID=$(field '.target_system_id // ""')

    # Build the send side as an argument vector.
    SEND_ARGS=(zfs send -c)
    if [ -n "$START" ]; then
        SEND_ARGS+=(-I "${POOL}/${DATASET}@${START}")
    fi
    SEND_ARGS+=("${POOL}/${DATASET}@${END}")

    # And the receive side, which runs on the target over ssh.
    RECEIVE_ARGS=(zfs receive)
    if [ "$REQUIRES_ROLLBACK" = "true" ]; then
        # The target holds snapshots this source does not, taken after the
        # starting snapshot. -F discards them so the stream can be received.
        log "NOTE: $DATASET on $TARGET_HOST has diverged; -F will discard its local snapshots"
        RECEIVE_ARGS+=(-F)
    fi
    RECEIVE_ARGS+=(-s "${TARGET_POOL}/${TARGET_DATASET}")

    SSH_ARGS=(ssh)
    if [ "$TARGET_PORT" != "22" ]; then
        SSH_ARGS+=(-p "$TARGET_PORT")
    fi
    if [ -n "$TARGET_USER" ]; then
        SSH_ARGS+=("${TARGET_USER}@${TARGET_HOST}")
    else
        SSH_ARGS+=("$TARGET_HOST")
    fi

    log "Syncing $DATASET to $TARGET_HOST: ${START:-(full)}..$END"

    if [ "$DRY_RUN" = "true" ]; then
        log "DRY RUN: ${SEND_ARGS[*]} | ${SSH_ARGS[*]} ${RECEIVE_ARGS[*]}"
        EXECUTED=$((EXECUTED + 1))
        continue
    fi

    STARTED_AT=$(date +%s)
    if "${SEND_ARGS[@]}" | "${SSH_ARGS[@]}" "${RECEIVE_ARGS[@]}"; then
        DURATION=$(( $(date +%s) - STARTED_AT ))
        log "SUCCESS: $DATASET -> $TARGET_HOST in ${DURATION}s"
        EXECUTED=$((EXECUTED + 1))
        report_result "$GROUP_ID" "$DATASET" "$TARGET_SYSTEM_ID" "success" \
            "$START" "$END" "$DURATION" ""
    else
        DURATION=$(( $(date +%s) - STARTED_AT ))
        log "FAILED: $DATASET -> $TARGET_HOST after ${DURATION}s"
        FAILED=$((FAILED + 1))
        report_result "$GROUP_ID" "$DATASET" "$TARGET_SYSTEM_ID" "failed" \
            "$START" "$END" "$DURATION" "zfs send/receive exited non-zero"
    fi
done < <(echo "$INSTRUCTIONS" | jq -c '.datasets[]')

log "Sync run complete: $EXECUTED succeeded, $FAILED failed"

[ "$FAILED" -eq 0 ] || exit 1
exit 0
