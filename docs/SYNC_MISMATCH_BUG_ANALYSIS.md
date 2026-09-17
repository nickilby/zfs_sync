# Sync Mismatch Detection Bug Analysis

> **Historical.** Kept for the reasoning, not as a description of the code.
>
> The diagnosis here is sound, but the fix it describes was never wired into
> the running service: the helper it names lived in `sync_validators.py` and
> nothing imported it. The rules are now implemented, and tested, in
> `zfs_sync/services/sync/policy.py`.

## Problem Description

The sync system is not detecting that SPOKE1 is behind HUB1 for the DATA1 dataset, even though SPOKE1 is missing many snapshots.

### Observed Behavior

- HUB1 has snapshots from 2025-09-04 to 2025-11-30
- SPOKE1 has snapshots from 2025-10-08 to 2025-11-04
- SPOKE1 is missing snapshots from 2025-11-05 onwards (26 days behind)
- The sync report script reports "No datasets require syncing"

### Expected Behavior

The system should detect that SPOKE1 is missing snapshots and generate sync instructions to sync from HUB1 to SPOKE1.

## Root Cause Analysis

The issue is in the `is_snapshot_out_of_sync_by_72h` function in `zfs_sync/services/sync_validators.py`. The function had a redundant check that was filtering snapshots incorrectly.

### The Bug

The function was checking:

```python
if snapshot_name in source_snapshot_names and is_midnight_snapshot(snapshot_name):
```

However, `source_snapshot_names` is already filtered to only midnight snapshots (from `sync_coordination.py` line 696-702), so the `is_midnight_snapshot` check was redundant. More importantly, this could cause issues if the filtering logic wasn't working correctly.

### The Fix

1. Removed the redundant `is_midnight_snapshot` check since `source_snapshot_names` and `target_snapshot_names` are already filtered to midnight snapshots
1. Added debug logging to help diagnose sync issues in the future
1. Improved comments to clarify that the snapshot name sets are already filtered

## Test Case

A test case has been created in `tests/unit/test_services/test_sync_mismatch_detection.py` that reproduces the exact scenario:

- HUB1 (source) with snapshots from 2025-09-04 to 2025-11-30
- SPOKE1 (target) with snapshots from 2025-10-08 to 2025-11-04
- Verifies that the system detects SPOKE1 as out of sync and generates sync instructions

## Verification

To verify the fix works:

1. Run the test: `pytest tests/unit/test_services/test_sync_mismatch_detection.py -v`
1. Check the sync instructions API endpoint to see if it now detects the mismatch
1. Review the debug logs to see the sync check results

## Additional Notes

The function `is_snapshot_out_of_sync_by_72h` is a guardrail that prevents syncing systems that are only slightly out of sync (\< 72 hours). The logic:

1. Finds the latest midnight snapshot on the source
1. Checks if the target has this snapshot (if yes, returns False - not out of sync)
1. Finds the latest midnight snapshot on the target
1. Calculates the time difference between the two
1. Returns True if the difference is > 72 hours

In the SPOKE1/HUB1 case:

- Latest HUB1: 2025-11-30-000000
- Latest SPOKE1: 2025-11-04-000000
- Time difference: 26 days = 624 hours > 72 hours
- Should return: True (out of sync)
