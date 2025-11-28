#!/usr/bin/env python3
"""
Test script to create sample data for snapshot comparison testing.

This script creates sample systems, snapshots, and sync groups matching
the L1S4DAT1 scenario (hqs7 vs hqs10 with different snapshot sets).
"""

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

# Add parent directory to path to import zfs_sync modules
sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy.orm import Session

from zfs_sync.database import get_db
from zfs_sync.database.models import SnapshotModel, SyncGroupSystemModel
from zfs_sync.database.repositories import (
    SystemRepository,
    SnapshotRepository,
    SyncGroupRepository,
)


def create_sample_data():
    """Create sample systems, snapshots, and sync groups."""
    db: Session = next(get_db())

    try:
        # Create systems
        system_repo = SystemRepository(db)
        snapshot_repo = SnapshotRepository(db)
        sync_group_repo = SyncGroupRepository(db)

        # Get or create hqs7 system
        hqs7 = system_repo.get_by_hostname("hqs7")
        if not hqs7:
            hqs7 = system_repo.create(
                hostname="hqs7",
                platform="linux",
                api_key=str(uuid4()),
                connectivity_status="online",
            )
            print(f"Created system: {hqs7.hostname} ({hqs7.id})")
        else:
            print(f"Using existing system: {hqs7.hostname} ({hqs7.id})")

        # Get or create hqs10 system
        hqs10 = system_repo.get_by_hostname("hqs10")
        if not hqs10:
            hqs10 = system_repo.create(
                hostname="hqs10",
                platform="linux",
                api_key=str(uuid4()),
                connectivity_status="online",
            )
            print(f"Created system: {hqs10.hostname} ({hqs10.id})")
        else:
            print(f"Using existing system: {hqs10.hostname} ({hqs10.id})")

        # Create snapshots for hqs7 (hqs7p1/L1S4DAT1)
        # Based on user's data: snapshots from 2025-10-08 to 2025-11-04
        hqs7_snapshots = []
        base_date = datetime(2025, 10, 8, tzinfo=timezone.utc)
        for i in range(28):  # 28 days from Oct 8 to Nov 4
            snapshot_date = base_date + timedelta(days=i)
            snapshot_name = snapshot_date.strftime("%Y-%m-%d-%H%M%S")
            if i == 27:  # Nov 4
                snapshot_name = "2025-11-04-000000"

            snapshot_name_full = f"hqs7p1/L1S4DAT1@{snapshot_name}"
            # Check if snapshot already exists
            existing = (
                db.query(SnapshotModel)
                .filter(
                    SnapshotModel.name == snapshot_name_full, SnapshotModel.system_id == hqs7.id
                )
                .first()
            )
            if not existing:
                snapshot = snapshot_repo.create(
                    name=snapshot_name_full,
                    pool="hqs7p1",
                    dataset="L1S4DAT1",
                    system_id=hqs7.id,
                    timestamp=snapshot_date,
                )
                hqs7_snapshots.append(snapshot)
            else:
                hqs7_snapshots.append(existing)

        # Add the 2025-11-03-120000 snapshot
        snapshot_date = datetime(2025, 11, 3, 12, 0, 0, tzinfo=timezone.utc)
        snapshot_name_full = "hqs7p1/L1S4DAT1@2025-11-03-120000"
        existing = (
            db.query(SnapshotModel)
            .filter(SnapshotModel.name == snapshot_name_full, SnapshotModel.system_id == hqs7.id)
            .first()
        )
        if not existing:
            snapshot = snapshot_repo.create(
                name=snapshot_name_full,
                pool="hqs7p1",
                dataset="L1S4DAT1",
                system_id=hqs7.id,
                timestamp=snapshot_date,
            )
            hqs7_snapshots.append(snapshot)
        else:
            hqs7_snapshots.append(existing)

        print(f"Created {len(hqs7_snapshots)} snapshots for hqs7")

        # Create snapshots for hqs10 (hqs10p1/L1S4DAT1)
        # Based on user's data: snapshots from 2025-08-07 to 2025-11-27
        # But focusing on the overlapping period (Oct onwards)
        hqs10_snapshots = []
        # Weekly snapshots from Aug to Oct
        weekly_base = datetime(2025, 8, 7, tzinfo=timezone.utc)
        for i in range(10):  # 10 weekly snapshots
            snapshot_date = weekly_base + timedelta(weeks=i)
            snapshot_name = snapshot_date.strftime("%Y-%m-%d-%H%M%S")
            snapshot_name_full = f"hqs10p1/L1S4DAT1@{snapshot_name}"
            existing = (
                db.query(SnapshotModel)
                .filter(
                    SnapshotModel.name == snapshot_name_full, SnapshotModel.system_id == hqs10.id
                )
                .first()
            )
            if not existing:
                snapshot = snapshot_repo.create(
                    name=snapshot_name_full,
                    pool="hqs10p1",
                    dataset="L1S4DAT1",
                    system_id=hqs10.id,
                    timestamp=snapshot_date,
                )
                hqs10_snapshots.append(snapshot)
            else:
                hqs10_snapshots.append(existing)

        # Daily snapshots from Oct 21 onwards (matching hqs7's pattern)
        daily_base = datetime(2025, 10, 21, tzinfo=timezone.utc)
        for i in range(38):  # 38 days from Oct 21 to Nov 27
            snapshot_date = daily_base + timedelta(days=i)
            snapshot_name = snapshot_date.strftime("%Y-%m-%d-%H%M%S")
            if i == 0:  # Oct 21
                snapshot_name = "2025-10-21-000000"
            elif i == 17:  # Nov 7
                snapshot_name = "2025-11-07-000000"
            elif i == 37:  # Nov 27
                snapshot_name = "2025-11-27-000000"

            snapshot_name_full = f"hqs10p1/L1S4DAT1@{snapshot_name}"
            existing = (
                db.query(SnapshotModel)
                .filter(
                    SnapshotModel.name == snapshot_name_full, SnapshotModel.system_id == hqs10.id
                )
                .first()
            )
            if not existing:
                snapshot = snapshot_repo.create(
                    name=snapshot_name_full,
                    pool="hqs10p1",
                    dataset="L1S4DAT1",
                    system_id=hqs10.id,
                    timestamp=snapshot_date,
                )
                hqs10_snapshots.append(snapshot)
            else:
                hqs10_snapshots.append(existing)

        # Add the 2025-11-03-120000 snapshot
        snapshot_date = datetime(2025, 11, 3, 12, 0, 0, tzinfo=timezone.utc)
        snapshot_name_full = "hqs10p1/L1S4DAT1@2025-11-03-120000"
        existing = (
            db.query(SnapshotModel)
            .filter(SnapshotModel.name == snapshot_name_full, SnapshotModel.system_id == hqs10.id)
            .first()
        )
        if not existing:
            snapshot = snapshot_repo.create(
                name=snapshot_name_full,
                pool="hqs10p1",
                dataset="L1S4DAT1",
                system_id=hqs10.id,
                timestamp=snapshot_date,
            )
            hqs10_snapshots.append(snapshot)
        else:
            hqs10_snapshots.append(existing)

        # Add the 2025-11-04-120000 snapshot (hqs10 has this, hqs7 doesn't)
        snapshot_date = datetime(2025, 11, 4, 12, 0, 0, tzinfo=timezone.utc)
        snapshot_name_full = "hqs10p1/L1S4DAT1@2025-11-04-120000"
        existing = (
            db.query(SnapshotModel)
            .filter(SnapshotModel.name == snapshot_name_full, SnapshotModel.system_id == hqs10.id)
            .first()
        )
        if not existing:
            snapshot = snapshot_repo.create(
                name=snapshot_name_full,
                pool="hqs10p1",
                dataset="L1S4DAT1",
                system_id=hqs10.id,
                timestamp=snapshot_date,
            )
            hqs10_snapshots.append(snapshot)
        else:
            hqs10_snapshots.append(existing)

        print(f"Created {len(hqs10_snapshots)} snapshots for hqs10")

        # Get or create sync group
        sync_group = sync_group_repo.get_by_name("L1S4DAT1 Sync Group")
        if not sync_group:
            sync_group = sync_group_repo.create(
                name="L1S4DAT1 Sync Group",
                description="Test sync group for L1S4DAT1 dataset",
                enabled=True,
            )
            print(f"Created sync group: {sync_group.name} ({sync_group.id})")
        else:
            print(f"Using existing sync group: {sync_group.name} ({sync_group.id})")

        # Associate systems with sync group (check if already associated)
        existing_assoc1 = (
            db.query(SyncGroupSystemModel)
            .filter(
                SyncGroupSystemModel.sync_group_id == sync_group.id,
                SyncGroupSystemModel.system_id == hqs7.id,
            )
            .first()
        )
        if not existing_assoc1:
            db.add(
                SyncGroupSystemModel(
                    sync_group_id=sync_group.id,
                    system_id=hqs7.id,
                )
            )

        existing_assoc2 = (
            db.query(SyncGroupSystemModel)
            .filter(
                SyncGroupSystemModel.sync_group_id == sync_group.id,
                SyncGroupSystemModel.system_id == hqs10.id,
            )
            .first()
        )
        if not existing_assoc2:
            db.add(
                SyncGroupSystemModel(
                    sync_group_id=sync_group.id,
                    system_id=hqs10.id,
                )
            )

        db.commit()

        print("\nSummary:")
        print(f"  Systems: hqs7 ({hqs7.id}), hqs10 ({hqs10.id})")
        print(f"  Snapshots: hqs7={len(hqs7_snapshots)}, hqs10={len(hqs10_snapshots)}")
        print(f"  Sync Group: {sync_group.id}")
        print("\nYou can now test the comparison endpoints:")
        print(
            f"  GET /api/v1/snapshots/compare-dataset?dataset=L1S4DAT1&system_ids={hqs7.id}&system_ids={hqs10.id}"
        )
        print(f"  GET /api/v1/sync/groups/{sync_group.id}/analysis")

    except Exception as e:
        db.rollback()
        print(f"Error creating sample data: {e}", file=sys.stderr)
        raise
    finally:
        db.close()


if __name__ == "__main__":
    print("Creating sample data for snapshot comparison testing...")
    create_sample_data()
    print("\nDone!")
