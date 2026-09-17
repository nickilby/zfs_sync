#!/bin/bash
#
# znapzend -> zfs_sync report hook
#
# Reports this host's current snapshot inventory to the witness service. Run it
# after znapzend has taken or expired snapshots, so the witness sees what
# actually exists rather than what it last heard about.
#
# znapzend has no post-snapshot hook of its own, so schedule this alongside it:
#
#   # /etc/cron.d/zfs-sync-report
#   */15 * * * * root /usr/local/bin/znapzend_report_hook.sh >/dev/null 2>&1
#
# Reporting more often than znapzend snapshots is harmless -- the endpoint is
# idempotent, so an unchanged inventory stores nothing new.
#
# Why the witness needs this at all: znapzend owns creation and retention, and
# it prunes. A snapshot the witness still believes exists can be proposed as an
# incremental base after znapzend has expired it, and the resulting send fails
# on the wire. Keeping the inventory current is what prevents that.
#
# Environment:
#   WITNESS_API_URL  Base URL of the witness service (default http://localhost:8000)
#   SYSTEM_ID        This host's registered UUID (required)
#   API_KEY          This host's API key (required)
#   ZFS_DATASETS     Space-separated datasets to report. Defaults to every
#                    dataset znapzend manages on this host.

set -euo pipefail

WITNESS_API_URL="${WITNESS_API_URL:-http://localhost:8000}"
SYSTEM_ID="${SYSTEM_ID:-}"
API_KEY="${API_KEY:-}"
ZFS_DATASETS="${ZFS_DATASETS:-}"

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*"
}

die() {
    log "ERROR: $*"
    exit 1
}

command -v jq >/dev/null 2>&1 || die "jq is required but not installed"
command -v zfs >/dev/null 2>&1 || die "zfs is required but not installed"
[ -n "$SYSTEM_ID" ] || die "SYSTEM_ID is required"
[ -n "$API_KEY" ] || die "API_KEY is required"

# ---------------------------------------------------------------------------
# Which datasets to report
# ---------------------------------------------------------------------------

if [ -z "$ZFS_DATASETS" ]; then
    # znapzend records its configuration in ZFS user properties under the
    # org.znapzend namespace, so the datasets it manages can be discovered
    # rather than listed by hand.
    ZFS_DATASETS=$(zfs get -H -o name -s local,received org.znapzend:enabled 2>/dev/null || true)
    if [ -z "$ZFS_DATASETS" ]; then
        die "No znapzend-managed datasets found. Set ZFS_DATASETS explicitly."
    fi
    log "Discovered znapzend-managed datasets: $(echo "$ZFS_DATASETS" | tr '\n' ' ')"
fi

# ---------------------------------------------------------------------------
# Build the inventory
# ---------------------------------------------------------------------------

# One request per dataset. Each is then a complete report of what it covers,
# which is what reconcile=true asserts -- a batch that only partly covers a
# dataset must not reconcile, or it would prune the snapshots it omitted.
TOTAL_CREATED=0
TOTAL_DELETED=0
FAILED=0

while IFS= read -r dataset; do
    [ -n "$dataset" ] || continue

    pool="${dataset%%/*}"

    # creation is reported as a unix timestamp so no date parsing is needed.
    payload=$(zfs list -H -p -t snapshot -o name,creation,used,referenced \
                  -s creation -d 1 "$dataset" 2>/dev/null \
        | jq -R -s --arg pool "$pool" --arg dataset "$dataset" --arg system "$SYSTEM_ID" '
            split("\n")
            | map(select(length > 0))
            | map(split("\t"))
            | map({
                name: .[0],
                pool: $pool,
                dataset: $dataset,
                timestamp: (.[1] | tonumber | todate),
                used: (.[2] | tonumber),
                referenced: (.[3] | tonumber),
                size: (.[2] | tonumber),
                system_id: $system
              })')

    count=$(echo "$payload" | jq 'length')
    if [ "$count" -eq 0 ]; then
        log "$dataset: no snapshots"
        continue
    fi

    response=$(curl -sS -X POST \
        "${WITNESS_API_URL}/api/v1/snapshots/batch?reconcile=true" \
        -H "X-API-Key: $API_KEY" \
        -H "Content-Type: application/json" \
        -d "$payload") || {
        log "$dataset: request failed"
        FAILED=$((FAILED + 1))
        continue
    }

    created=$(echo "$response" | jq -r '.created // 0')
    updated=$(echo "$response" | jq -r '.updated // 0')
    deleted=$(echo "$response" | jq -r '.deleted // 0')
    rejected=$(echo "$response" | jq -r '.failed | length')

    TOTAL_CREATED=$((TOTAL_CREATED + created))
    TOTAL_DELETED=$((TOTAL_DELETED + deleted))

    log "$dataset: $count snapshot(s) -> $created created, $updated updated, $deleted pruned"

    if [ "$rejected" -gt 0 ]; then
        FAILED=$((FAILED + rejected))
        echo "$response" | jq -r '.failed[] | "  REJECTED \(.name): \(.error)"'
    fi
done <<< "$ZFS_DATASETS"

log "Reported: $TOTAL_CREATED new, $TOTAL_DELETED pruned, $FAILED failed"

[ "$FAILED" -eq 0 ]
