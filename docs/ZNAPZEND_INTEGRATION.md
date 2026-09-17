# Running zfs_sync alongside znapzend

## Who does what

znapzend and zfs_sync overlap, and it is worth being explicit about the split
rather than discovering it in production.

| | znapzend | zfs_sync |
|---|---|---|
| Takes snapshots | Yes, on its own schedule | No |
| Expires snapshots | Yes, per its retention plan | No |
| Replicates | Yes, to its configured destinations | Yes, where znapzend is not already doing it |
| Knows about one host | Yes | — |
| Knows about the whole fleet | No | Yes |
| Answers "did the backup land?" | No | Yes |

znapzend is a daemon per host: each one knows its own datasets and its own
destinations, and nothing knows whether the fleet as a whole is consistent.
zfs_sync is the part that does — it holds every host's inventory, compares
them, and reports where a dataset is behind and why.

The short version: **let znapzend create and expire snapshots. Let zfs_sync
tell you whether the fleet is actually in the state you think it is.**

## Setup

### 1. Configure the snapshot naming pattern

This is the one setting that matters, and getting it wrong is quiet rather than
loud.

znapzend's default `tsformat` is `%Y-%m-%d-%H%M%S`, and it takes snapshots
throughout the day. zfs_sync's default pattern only matches midnight snapshots,
a convention inherited from its original deployment. Under that default, a
znapzend host taking four snapshots a day has three of them ignored: planning
still works, but it targets a snapshot up to 18 hours older than the newest one
available, so the host looks further behind than it is.

Set the pattern to match what znapzend produces:

```yaml
# config/zfs_sync.yaml
snapshot_anchor_pattern: '^\d{4}-\d{2}-\d{2}-\d{6}$'
```

or:

```bash
export ZFS_SYNC_SNAPSHOT_ANCHOR_PATTERN='^\d{4}-\d{2}-\d{2}-\d{6}$'
```

This pattern also matches the legacy midnight convention, so a mixed fleet —
some hosts on znapzend, some still taking midnight-only snapshots — works under
a single setting.

If you have changed `org.znapzend:tsformat`, change this to match. An
uncompilable pattern is rejected at startup rather than mid-sync, and a pattern
that matches nothing shows up per pair as `no_eligible_ending_snapshot` rather
than as an empty result with no explanation.

Set `snapshot_anchor_pattern: ''` to accept any snapshot name, including
manually created ones. That is usually not what you want: a manual
`@before-upgrade` snapshot would then be eligible to end a send window.

### 2. Report inventories to the witness

znapzend has no post-snapshot hook, so schedule the reporting script alongside
it:

```bash
install -m 0755 docs/templates/znapzend_report_hook.sh /usr/local/bin/

cat > /etc/cron.d/zfs-sync-report <<'EOF'
WITNESS_API_URL=https://witness.internal:8000
SYSTEM_ID=<this host's registered UUID>
API_KEY=<this host's API key>
*/15 * * * * root /usr/local/bin/znapzend_report_hook.sh >/dev/null 2>&1
EOF
```

The hook discovers znapzend-managed datasets from the `org.znapzend:enabled`
property, so it does not need a dataset list. Reporting more often than
znapzend snapshots is harmless: ingestion is idempotent, so an unchanged
inventory stores nothing new.

### 3. Decide whether zfs_sync should replicate

Two workable arrangements:

**znapzend replicates, zfs_sync verifies.** Configure znapzend's destinations
as usual and leave the hosts out of a directional sync group. zfs_sync ingests
both sides' inventories and reports drift, but issues no instructions. Use this
where znapzend's replication already works and you want visibility over it.

**zfs_sync replicates.** Put the hosts in a directional sync group with a hub,
and let it plan the transfers. Use this for paths znapzend is not covering —
typically fan-out from a hub to several targets, where each spoke needs a
different incremental base.

You can mix the two per dataset. Where znapzend has already replicated,
zfs_sync reports `in_sync_within_window` or `base_equals_end` and issues
nothing, so the two do not duplicate a transfer.

## Retention, and why the inventory must stay current

znapzend expires snapshots. zfs_sync chooses an incremental base from the
snapshots it believes both sides hold, so a base that znapzend has since pruned
produces a `zfs send -I` that fails on the wire.

Two things keep this from biting:

- The report hook reconciles, so an expired snapshot is removed from the
  witness's record on the next run rather than lingering.
- Planning happens per request against current state, so the next plan selects
  a base that still exists.

If znapzend prunes every snapshot the two sides shared, zfs_sync reports
`no_common_base` and plans a full send rather than a broken incremental one.

Set the reporting interval shorter than the retention window. The failure mode
if you do not is a failed send, which the feedback loop records as such — not
silent data loss — but it is avoidable.

## `zfs receive -F` and znapzend destinations

If a target holds snapshots the source does not — because znapzend took its own
there, or because a previous replication diverged — the receive needs `-F`,
which **discards those snapshots**.

zfs_sync flags this rather than doing it quietly: the instruction carries
`requires_rollback: true`, the client logs it before running, and
`/decisions` reports the pair as `target_diverged`.

If your znapzend targets take their own local snapshots that are not
reproducible from the hub, review those instructions before enabling automatic
execution.

## Checking it works

```bash
# Every pair the planner considered, and why.
curl -H "X-API-Key: $API_KEY" \
  "$WITNESS_API_URL/api/v1/sync/groups/$GROUP_ID/decisions" | jq '.decisions'
```

What you are looking for:

| Reason | Meaning |
|---|---|
| `in_sync_within_window` | Nothing to do. The healthy answer. |
| `no_eligible_ending_snapshot` | Nothing old enough to send — or the naming pattern does not match what znapzend produces. Check step 1. |
| `no_common_base` | The two sides share nothing; a full send is planned. Expect this on a new target, or after aggressive retention. |
| `target_diverged` | The target has its own snapshots. The sync will use `-F`. |
| `base_equals_end` | Already current, including anything znapzend replicated itself. |

If every dataset reports `no_eligible_ending_snapshot`, the naming pattern is
almost certainly the cause rather than the fleet being out of date.
