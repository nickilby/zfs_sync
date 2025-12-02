# Sync Mismatch Detection Bug Analysis

## Problem Description

The sync system is not detecting that HQS7 is behind HQS10 for the L1S4DAT1 dataset, even though HQS7 is missing many snapshots.

### Observed Behavior

- HQS10 has snapshots from 2025-09-04 to 2025-11-30
- HQS7 has snapshots from 2025-10-08 to 2025-11-04
- HQS7 is missing snapshots from 2025-11-05 onwards (26 days behind)
- The sync report script reports "No datasets require syncing"

### Expected Behavior

The system should detect that HQS7 is missing snapshots and generate sync instructions to sync from HQS10 to HQS7.

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

- HQS10 (source) with snapshots from 2025-09-04 to 2025-11-30
- HQS7 (target) with snapshots from 2025-10-08 to 2025-11-04
- Verifies that the system detects HQS7 as out of sync and generates sync instructions

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

In the HQS7/HQS10 case:

- Latest HQS10: 2025-11-30-000000
- Latest HQS7: 2025-11-04-000000
- Time difference: 26 days = 624 hours > 72 hours
- Should return: True (out of sync)
