# Mismatch Filtering Analysis

## Problem Summary

The system detects 1525 mismatches for sync group `276231c1-1867-428f-b122-4bc5aaa47ad3` but reports "no datasets to sync". There are also many `orphaned_snapshot` conflicts for system `72c0c3d5-ca09-4174-a2b2-46cf3842d99a` on dataset `M1S2MIR1`.

## Root Cause Analysis

### Primary Issue: 72-Hour Check Filters All Mismatches Per Dataset

The 72-hour validation check in `determine_sync_actions()` (lines 358-369 of `sync_coordination.py`) is filtering out all mismatches for a dataset if the latest midnight snapshots between source and target systems are within 72 hours of each other.

**The Problem (current behaviour):**

1. The check compares only the **latest midnight snapshots** between source and target
1. If those snapshots are within 72 hours, **ALL mismatches for that dataset** are filtered out
1. This happens even if there are many missing intermediate snapshots between the latest snapshots

**Example Scenario:**

- Source has snapshots: `2025-11-30-000000`, `2025-12-01-000000`, `2025-12-02-000000`, `2025-12-03-000000`
- Target has snapshots: `2025-11-30-000000` (missing 2025-12-01, 2025-12-02, 2025-12-03)
- Latest source: `2025-12-03-000000`
- Latest target: `2025-11-30-000000`
- Time difference: 3 days = 72 hours
- If the check uses `> 72 hours` (not `>=`), it will filter out ALL mismatches for this dataset
- Even though target is missing 3 snapshots!

### Secondary Issue: Orphaned Snapshots May Affect Comparison

Orphaned snapshots (snapshots that exist on one system but not others, with no common ancestor) can affect the 72-hour check:

1. If the target has orphaned snapshots that are newer than the source's latest, the comparison might show they're "in sync"
1. The check doesn't account for whether snapshots are orphaned when comparing

## Diagnostic Logging Added

### In `sync_coordination.py` (`determine_sync_actions`):

1. **Filter Statistics**: Tracks how many mismatches are filtered by each condition:

   - `72h_check`: Filtered by 72-hour validation
   - `missing_source_system`: Source system not found
   - `missing_pool`: Could not determine pool
   - `missing_target_system`: Target system not found
   - `orphan_dataset`: Target has no snapshots (orphan dataset)
   - `command_generation_failed`: Failed to generate sync command
   - `passed`: Successfully created actions

1. **Detailed Logging for 72-Hour Check**:

   - Logs when mismatches are filtered by 72-hour check
   - Shows latest midnight snapshots being compared
   - Shows timestamps and time differences
   - Warns when many mismatches are filtered

1. **Logging for Other Filter Conditions**:

   - Each filter condition now logs with `[FILTER]` prefix
   - Includes dataset, snapshot, source system, and target system information

### In `sync_validators.py` (`is_snapshot_out_of_sync_by_hours`):

1. **Orphaned Snapshot Detection**:

   - Checks if target's latest snapshot exists on source
   - Warns if target's latest snapshot doesn't exist on source (orphaned)
   - Logs comparison details including orphaned snapshot status

1. **Enhanced Debug Logging**:

   - Logs when target has the latest source snapshot
   - Notes that intermediate snapshots may still be missing

## Test Case Added

Created `test_orphaned_snapshots_filter_mismatches()` in `test_sync_mismatch_detection.py` that:

- Reproduces the orphaned snapshot scenario
- Verifies mismatches are detected
- Captures diagnostic output to understand filtering behavior
- Tests the boundary case (exactly 72 hours difference)

## Expected Diagnostic Output

When running the system, you should now see:

1. **Filter Statistics Summary**:

   ```
   Sync action filter statistics for sync group <id>: 
   Total mismatches processed: 1525, 
   Filtered by 72h_check: 1525, 
   Filtered by missing_source_system: 0, 
   Filtered by missing_pool: 0, 
   Filtered by missing_target_system: 0, 
   Filtered by orphan_dataset: 0, 
   Filtered by command_generation_failed: 0, 
   Passed (actions created): 0
   ```

1. **Individual Filter Warnings**:

   ```
   [FILTER] 72h_check: Skipping mismatch for dataset=M1S2MIR1 snapshot=2025-12-01-000000 
   source_system=<id> target_system=<id>. 
   Source latest midnight: 2025-12-03-000000 (2025-12-03T00:00:00+00:00), 
   Target latest midnight: 2025-11-30-000000 (2025-11-30T00:00:00+00:00). 
   Systems appear within 72-hour sync window.
   ```

1. **Orphaned Snapshot Warnings** (if applicable):

   ```
   Target's latest midnight snapshot 2025-12-03-000000 (2025-12-03T00:00:00+00:00) 
   does not exist on source. This may be an orphaned snapshot.
   ```

## Target Behaviour (what we actually want)

The project’s intended policy is:

- Only send **snapshots whose timestamps are at least 72 hours older than “now”**.
- This guarantees that, after a sync run, the target will lag the source by **no more than ~72 hours in absolute time**, regardless of how far behind it started.
- The decision about *whether* a dataset is out of sync can still use `is_snapshot_out_of_sync_by_72h()` (latest-midnight comparison), but the decision about **which snapshot to send as the ending point** is tied to “now − 72h”.

Concretely, for the L1S4DAT1 example:

- Comparison time: `2025-12-04T09:13:30Z` (from `/snapshots/compare-dataset`).

- Source latest snapshots up to that time include `2025-12-01-000000`, `2025-12-01-120000`, `2025-12-02-000000`, `2025-12-02-120000`, `2025-12-03-000000`, `2025-12-03-120000`.

- `now - 72h` is approximately `2025-12-01T09:13Z`.

- Therefore:

  - `2025-12-01-000000` (midnight) **is older than 72h** and is allowed as an ending snapshot.
  - `2025-12-01-120000` and later snapshots are **too new** and must **not** be included yet.

- The correct incremental send should be:

  - **Starting snapshot**: the last common snapshot between source and target (`2025-10-30-000000`).
  - **Ending snapshot**: the latest snapshot on the source whose timestamp ≤ `now − 72h` (`2025-12-01-000000` in this example).

Resulting command:

- `zfs send -c -I hqs10p1/L1S4DAT1@2025-10-30-000000 hqs10p1/L1S4DAT1@2025-12-01-000000 | ssh hqs7-san "zfs receive -s hqs7p1/L1S4DAT1"`

This means:

- `is_snapshot_out_of_sync_by_72h()` answers **“are we sufficiently out of sync to bother?”** using latest midnight snapshots.
- A new helper (in `sync_validators`) will answer **“what is the latest snapshot we are allowed to send, given the now−72h rule?”** and is applied when building actions/instructions.

## Potential Fixes (design options considered)

### Option 1: Check Per-Snapshot Instead of Per-Dataset

Instead of filtering all mismatches for a dataset based on the latest midnight snapshots, check each missing snapshot individually:

- For each missing snapshot, check if it's more than 72 hours old
- Only filter individual snapshots that are within 72 hours
- This would allow syncing of older missing snapshots even if latest snapshots are close

**Pros:**

- More granular control
- Allows syncing of older missing snapshots
- Better handles cases with many missing intermediate snapshots

**Cons:**

- More complex logic
- May generate many small sync actions instead of one consolidated action

### Option 2: Adjust the 72-Hour Threshold

Change the threshold or make it configurable:

- Reduce threshold (e.g., 24 hours instead of 72)
- Make threshold configurable per sync group
- Use different thresholds for different scenarios

**Pros:**

- Simple change
- Maintains current architecture

**Cons:**

- Doesn't solve the fundamental issue (per-dataset vs per-snapshot)
- May cause other issues if threshold is too low

### Option 3: Skip 72-Hour Check for Missing Intermediate Snapshots

If there are missing snapshots between the latest source and target snapshots, skip the 72-hour check:

- Detect if there are gaps in the snapshot sequence
- If gaps exist, allow syncing regardless of 72-hour check
- Only apply 72-hour check when snapshots are sequential

**Pros:**

- Addresses the core issue
- Maintains guardrail for sequential snapshots

**Cons:**

- More complex logic
- Need to detect gaps in snapshot sequences

### Option 4: Special Handling for Orphaned Snapshots

When orphaned snapshots are detected, use different comparison logic:

- If target has orphaned snapshots, compare against source's latest that exists on target
- Or ignore orphaned snapshots when determining latest snapshot for comparison

**Pros:**

- Addresses orphaned snapshot interference
- More accurate comparison

**Cons:**

- Requires conflict detection to run before mismatch detection
- More complex integration

## Recommended Next Steps

1. **Run the system with diagnostic logging** to confirm the root cause
1. **Review the filter statistics** to see how many mismatches are filtered by each condition
1. **Analyze the 72-hour check warnings** to understand the time differences
1. **Decide on a fix approach** based on the diagnostic output
1. **Implement the chosen fix** and verify with the test case

## Files Modified

1. `zfs_sync/services/sync_coordination.py`
   - Added comprehensive diagnostic logging.
   - Refactored the 72-hour guardrail to:
     - Use `is_snapshot_out_of_sync_by_72h()` only as a *pair-level* “are we out of sync?” check.
     - Use `get_latest_allowed_snapshot_before_now()` to cap the ending snapshot for each (source, target, dataset) pair under the now−72h rule.
     - Filter individual mismatches whose snapshot names are newer than the allowed latest, instead of dropping entire datasets.
1. `zfs_sync/services/sync_validators.py`
   - Added orphaned snapshot detection and logging to `is_snapshot_out_of_sync_by_hours()`.
   - Introduced `get_latest_allowed_snapshot_before_now()` to implement the “only send snapshots at least 72 hours older than now” policy.
1. `tests/unit/test_services/test_sync_mismatch_detection.py`
   - Added a test for the orphaned snapshot scenario.
   - Added `test_l1s4dat1_72h_gate_generates_expected_command`, which:
     - Builds the L1S4DAT1 snapshot sets as seen in production.
     - Asserts that `get_sync_instructions()` for the lagging system:
       - Picks `2025-10-30-000000` as the starting snapshot (last common).
       - Picks `2025-12-01-000000` as the ending snapshot (latest allowed under now−72h).
       - Generates an incremental `zfs send -c -I ...` command from the starting to the ending snapshot.
