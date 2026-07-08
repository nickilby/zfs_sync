"""Unit tests for sync query helpers."""

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import List, Optional
from uuid import UUID, uuid4

from zfs_sync.services.sync_queries import (
    calculate_priority,
    find_incremental_base_by_dataset_name,
    find_snapshot_id,
    get_datasets_for_systems,
)


@dataclass
class SnapshotStub:
    """Simple snapshot value object used by query helper tests."""

    id: UUID
    name: str
    pool: str
    dataset: str
    system_id: UUID
    timestamp: datetime
    size: Optional[int] = None


class SnapshotRepoStub:
    """Repository stub implementing the minimal query surface used by sync_queries."""

    def __init__(self, snapshots: List[SnapshotStub]):
        self._snapshots = snapshots

    def get_by_system(self, system_id: UUID):
        return [s for s in self._snapshots if s.system_id == system_id]

    def get_by_pool_dataset(self, pool: str, dataset: str, system_id: Optional[UUID] = None):
        rows = [s for s in self._snapshots if s.pool == pool and s.dataset == dataset]
        if system_id is not None:
            rows = [s for s in rows if s.system_id == system_id]
        return rows


class ComparisonStub:
    """Comparison service stub with snapshot name extraction only."""

    @staticmethod
    def _extract_snapshot_name(full_name: str) -> str:
        return full_name.split("@", 1)[1] if "@" in full_name else full_name


def _snapshot(pool: str, dataset: str, snapshot_name: str, system_id: UUID, ts: datetime):
    return SnapshotStub(
        id=uuid4(),
        name=f"{pool}/{dataset}@{snapshot_name}",
        pool=pool,
        dataset=dataset,
        system_id=system_id,
        timestamp=ts,
        size=1024,
    )


def test_get_datasets_for_systems_groups_pool_and_system_mapping():
    """Dataset mapping should include pool/system tuples without duplicates."""
    s1 = uuid4()
    s2 = uuid4()
    snapshots = [
        _snapshot("tankA", "data", "2026-01-01-000000", s1, datetime.now(timezone.utc)),
        _snapshot("tankA", "data", "2026-01-02-000000", s1, datetime.now(timezone.utc)),
        _snapshot("tankB", "data", "2026-01-01-000000", s2, datetime.now(timezone.utc)),
    ]

    mapping = get_datasets_for_systems([s1, s2], SnapshotRepoStub(snapshots))

    assert "data" in mapping
    assert len(mapping["data"]) == 2
    assert ("tankA", s1) in mapping["data"]
    assert ("tankB", s2) in mapping["data"]


def test_find_incremental_base_by_dataset_name_uses_latest_common_midnight_snapshot():
    """Incremental base should be the newest common midnight snapshot across pools."""
    source = uuid4()
    target = uuid4()
    snapshots = [
        _snapshot("srcpool", "data", "2026-01-01-000000", source, datetime(2026, 1, 1, tzinfo=timezone.utc)),
        _snapshot("srcpool", "data", "2026-01-02-120000", source, datetime(2026, 1, 2, 12, tzinfo=timezone.utc)),
        _snapshot("srcpool", "data", "2026-01-03-000000", source, datetime(2026, 1, 3, tzinfo=timezone.utc)),
        _snapshot("dstpool", "data", "2026-01-01-000000", target, datetime(2026, 1, 1, tzinfo=timezone.utc)),
        _snapshot("dstpool", "data", "2026-01-02-000000", target, datetime(2026, 1, 2, tzinfo=timezone.utc)),
    ]

    base = find_incremental_base_by_dataset_name(
        dataset_name="data",
        target_system_id=target,
        target_pool="dstpool",
        source_system_id=source,
        source_pool="srcpool",
        snapshot_repo=SnapshotRepoStub(snapshots),
        comparison_service=ComparisonStub(),
    )

    assert base == "2026-01-01-000000"


def test_calculate_priority_favors_latest_and_widely_missing_snapshots():
    """Priority should include both latest-snapshot and missing-count boosts."""
    comparison = {
        "latest_snapshots": {"sys-a": {"name": "tank/data@daily-03"}},
        "missing_snapshots": {
            "sys-a": ["daily-03"],
            "sys-b": ["daily-03", "daily-02"],
        },
    }

    priority = calculate_priority("daily-03", comparison, ComparisonStub())

    assert priority == 40


def test_find_snapshot_id_returns_none_for_missing_snapshot():
    """Lookup should return None when a snapshot does not exist on the source system."""
    system_id = uuid4()
    snapshots = [
        _snapshot("tank", "data", "daily-01", system_id, datetime.now(timezone.utc)),
    ]

    snapshot_id = find_snapshot_id(
        pool="tank",
        dataset="data",
        snapshot_name="daily-99",
        system_id=system_id,
        snapshot_repo=SnapshotRepoStub(snapshots),
        comparison_service=ComparisonStub(),
    )

    assert snapshot_id is None
