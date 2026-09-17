"""Integrity failures must be distinguishable.

Every IntegrityError used to become ValueError("constraint violation"), which
discards the one thing a caller needs: whether the row was a duplicate or
referred to something that does not exist. That is why creating a sync group
with an unknown system_id surfaced as a 500 rather than a 400.
"""

import uuid
from datetime import datetime, timezone

import pytest

from zfs_sync.database.errors import (
    ConstraintViolation,
    DuplicateRecord,
    InvalidReference,
    RepositoryError,
    classify_integrity_error,
)
from zfs_sync.database.repositories import SnapshotRepository, SystemRepository


class FakeIntegrityError(Exception):
    def __init__(self, detail: str):
        self.orig = detail
        super().__init__(detail)


class TestClassification:
    def test_a_unique_violation(self):
        error = classify_integrity_error(
            FakeIntegrityError("UNIQUE constraint failed: snapshots.name"), "SnapshotModel"
        )
        assert isinstance(error, DuplicateRecord)

    def test_a_postgres_duplicate_key(self):
        error = classify_integrity_error(
            FakeIntegrityError('duplicate key value violates unique constraint "uq_x"'),
            "SnapshotModel",
        )
        assert isinstance(error, DuplicateRecord)

    def test_a_foreign_key_violation(self):
        error = classify_integrity_error(
            FakeIntegrityError("FOREIGN KEY constraint failed"), "SyncGroupModel"
        )
        assert isinstance(error, InvalidReference)

    def test_anything_else_is_a_generic_constraint_violation(self):
        error = classify_integrity_error(
            FakeIntegrityError("NOT NULL constraint failed: systems.hostname"), "SystemModel"
        )
        assert isinstance(error, ConstraintViolation)
        assert not isinstance(error, (DuplicateRecord, InvalidReference))

    def test_the_driver_detail_is_preserved(self):
        error = classify_integrity_error(
            FakeIntegrityError("UNIQUE constraint failed: snapshots.name"), "SnapshotModel"
        )
        assert "snapshots.name" in error.detail
        assert error.model == "SnapshotModel"

    def test_all_of_them_remain_value_errors(self):
        """Routes already catch ValueError; widening the type would have
        silently turned those 4xx responses into 500s."""
        for detail in ("UNIQUE constraint failed", "FOREIGN KEY constraint failed", "other"):
            error = classify_integrity_error(FakeIntegrityError(detail))
            assert isinstance(error, ValueError)
            assert isinstance(error, RepositoryError)


class TestAgainstTheDatabase:
    def test_a_duplicate_snapshot_raises_duplicate_record(self, test_db):
        systems = SystemRepository(test_db)
        snapshots = SnapshotRepository(test_db)
        system = systems.create(hostname="hub1", platform="linux", connectivity_status="online")
        fields = {
            "name": "hubpool1/DATA1@2025-01-01-000000",
            "pool": "hubpool1",
            "dataset": "DATA1",
            "timestamp": datetime(2025, 1, 1, tzinfo=timezone.utc),
            "size": 1024,
            "system_id": system.id,
        }
        snapshots.create(**fields)

        with pytest.raises(DuplicateRecord):
            snapshots.create(**fields)

    def test_a_duplicate_hostname_raises_duplicate_record(self, test_db):
        systems = SystemRepository(test_db)
        systems.create(hostname="hub1", platform="linux", connectivity_status="online")

        with pytest.raises(DuplicateRecord):
            systems.create(hostname="hub1", platform="linux", connectivity_status="online")

    def test_the_same_snapshot_on_another_system_is_fine(self, test_db):
        """Uniqueness is per system: a hub and its spokes hold the same names."""
        systems = SystemRepository(test_db)
        snapshots = SnapshotRepository(test_db)
        first = systems.create(hostname="hub1", platform="linux", connectivity_status="online")
        second = systems.create(hostname="spoke1", platform="linux", connectivity_status="online")

        for system in (first, second):
            snapshots.create(
                name="pool/DATA1@2025-01-01-000000",
                pool="pool",
                dataset="DATA1",
                timestamp=datetime(2025, 1, 1, tzinfo=timezone.utc),
                size=1024,
                system_id=system.id,
            )

        assert len(snapshots.get_all(limit=10)) == 2

    def test_one_sync_state_per_pair(self, test_db):
        from zfs_sync.database.repositories import SyncGroupRepository, SyncStateRepository

        systems = SystemRepository(test_db)
        groups = SyncGroupRepository(test_db)
        states = SyncStateRepository(test_db)

        system = systems.create(hostname="hub1", platform="linux", connectivity_status="online")
        group = groups.create(name="g1")
        fields = {
            "sync_group_id": group.id,
            "dataset": "DATA1",
            "system_id": system.id,
            "status": "out_of_sync",
        }
        states.create(**fields)

        with pytest.raises(DuplicateRecord):
            states.create(**fields)

    def test_an_unknown_foreign_key_is_reported_as_an_invalid_reference(self, test_db):
        """SQLite only enforces foreign keys when asked, so this is skipped
        where enforcement is off rather than asserted falsely."""
        from sqlalchemy import text

        test_db.execute(text("PRAGMA foreign_keys=ON"))
        snapshots = SnapshotRepository(test_db)

        try:
            snapshots.create(
                name="pool/DATA1@2025-01-01-000000",
                pool="pool",
                dataset="DATA1",
                timestamp=datetime(2025, 1, 1, tzinfo=timezone.utc),
                size=1024,
                system_id=uuid.uuid4(),
            )
        except InvalidReference:
            return
        except DuplicateRecord:  # pragma: no cover - would be a real defect
            pytest.fail("a dangling reference was reported as a duplicate")
        pytest.skip("foreign keys are not enforced on this connection")
