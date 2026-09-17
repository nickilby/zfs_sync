"""Snapshot ingestion: idempotent, authenticated, and scoped.

Reconciliation used to be system-wide: `delete_snapshots_not_in_set` removed
every snapshot for a system that was absent from the batch. A client reporting
a partial inventory -- one dataset, a paginated report, a run that crashed
halfway -- therefore destroyed the rest of that system's recorded history,
which is the state incremental bases are computed from.

Ingestion also called create() per row with no uniqueness, so every polling
cycle multiplied the records; and the endpoint required no authentication at
all, so anyone who could reach it could write inventories for any system and
thereby influence what the hub was told to send.
"""

from datetime import datetime, timezone

from fastapi import status

from zfs_sync.database.repositories import SnapshotRepository


def register(test_client, hostname):
    """Register a system and return its id and API key."""
    response = test_client.post(
        "/api/v1/systems",
        json={"hostname": hostname, "platform": "linux", "connectivity_status": "online"},
    )
    assert response.status_code == status.HTTP_201_CREATED
    body = response.json()
    return body["id"], body["api_key"]


def payload(system_id, dataset, day, pool="pool1"):
    return {
        "name": f"{pool}/{dataset}@2025-01-{day:02d}-000000",
        "pool": pool,
        "dataset": dataset,
        "timestamp": datetime(2025, 1, day, tzinfo=timezone.utc).isoformat(),
        "size": 1024,
        "system_id": str(system_id),
    }


def report(test_client, api_key, rows, reconcile=False):
    return test_client.post(
        "/api/v1/snapshots/batch",
        headers={"X-API-Key": api_key},
        params={"reconcile": str(reconcile).lower()},
        json=rows,
    )


def seed(test_client, api_key, system_id, datasets=("DATA1", "DATA2"), days=(1, 2, 3)):
    rows = [payload(system_id, dataset, day) for dataset in datasets for day in days]
    assert report(test_client, api_key, rows).status_code == status.HTTP_201_CREATED


class TestReportScope:
    def test_a_single_dataset_report_leaves_other_datasets_alone(
        self, test_client, test_db
    ):
        """The destructive case, now fixed.

        A client reporting only DATA1 must not remove DATA2, about which it
        said nothing.
        """
        system_id, api_key = register(test_client, "hub1")
        seed(test_client, api_key, system_id)
        repo = SnapshotRepository(test_db)
        assert len(repo.get_by_system(system_id, limit=None)) == 6

        response = report(
            test_client,
            api_key,
            [payload(system_id, "DATA1", day) for day in (1, 2, 3)],
            reconcile=True,
        )

        assert response.status_code == status.HTTP_201_CREATED
        body = response.json()
        assert body["deleted"] == 0
        assert body["scope"] == ["pool1/DATA1"]

        remaining = repo.get_by_system(system_id, limit=None)
        assert {s.dataset for s in remaining} == {"DATA1", "DATA2"}
        assert len(remaining) == 6

    def test_a_genuine_deletion_is_honoured_when_reconciling(
        self, test_client, test_db
    ):
        """Retention pruning must still be reflected, or the witness would
        keep proposing an incremental base that no longer exists."""
        system_id, api_key = register(test_client, "hub2")
        seed(test_client, api_key, system_id, datasets=("DATA1",))

        # Day 1 has been pruned on the host and is absent from the report.
        response = report(
            test_client,
            api_key,
            [payload(system_id, "DATA1", day) for day in (2, 3)],
            reconcile=True,
        )

        assert response.json()["deleted"] == 1
        remaining = SnapshotRepository(test_db).get_by_system(system_id, limit=None)
        assert {s.name for s in remaining} == {
            "pool1/DATA1@2025-01-02-000000",
            "pool1/DATA1@2025-01-03-000000",
        }

    def test_an_empty_report_prunes_nothing(self, test_client, test_db):
        """A client that reports nothing has not said its snapshots are gone."""
        system_id, api_key = register(test_client, "hub3")
        seed(test_client, api_key, system_id)

        response = report(test_client, api_key, [], reconcile=True)

        assert response.json()["deleted"] == 0
        assert len(SnapshotRepository(test_db).get_by_system(system_id, limit=None)) == 6

    def test_scope_distinguishes_pools(self, test_client, test_db):
        """The same dataset name can live on two pools; they reconcile apart."""
        system_id, api_key = register(test_client, "hub4")
        report(
            test_client,
            api_key,
            [payload(system_id, "DATA1", 1, pool="poolA"),
             payload(system_id, "DATA1", 1, pool="poolB")],
        )

        response = report(
            test_client,
            api_key,
            [payload(system_id, "DATA1", 2, pool="poolA")],
            reconcile=True,
        )

        assert response.json()["scope"] == ["poolA/DATA1"]
        remaining = SnapshotRepository(test_db).get_by_system(system_id, limit=None)
        pools = {s.pool for s in remaining}
        assert pools == {"poolA", "poolB"}, "poolB was untouched"


class TestIdempotency:
    def test_repeating_a_report_does_not_multiply_rows(self, test_client, test_db):
        """Every polling cycle used to add another copy of the whole inventory."""
        system_id, api_key = register(test_client, "hub5")
        rows = [payload(system_id, "DATA1", day) for day in (1, 2, 3)]

        first = report(test_client, api_key, rows).json()
        second = report(test_client, api_key, rows).json()
        third = report(test_client, api_key, rows).json()

        assert first["created"] == 3
        assert second == {**second, "created": 0, "updated": 3}
        assert third["created"] == 0
        assert len(SnapshotRepository(test_db).get_by_system(system_id, limit=None)) == 3

    def test_changed_facts_are_refreshed(self, test_client, test_db):
        """Identity fields match; everything else is updated in place."""
        system_id, api_key = register(test_client, "hub6")
        row = payload(system_id, "DATA1", 1)
        report(test_client, api_key, [row])

        row["size"] = 987654321
        report(test_client, api_key, [row])

        stored = SnapshotRepository(test_db).get_by_system(system_id, limit=None)
        assert len(stored) == 1
        assert stored[0].size == 987654321


class TestAuthentication:
    def test_an_unauthenticated_report_is_rejected(self, test_client, test_db):
        system_id, api_key = register(test_client, "hub7")
        seed(test_client, api_key, system_id, datasets=("DATA1",))

        response = test_client.post(
            "/api/v1/snapshots/batch", json=[payload(system_id, "DATA1", 9)]
        )

        assert response.status_code == status.HTTP_401_UNAUTHORIZED
        # And nothing was written or pruned.
        assert len(SnapshotRepository(test_db).get_by_system(system_id, limit=None)) == 3

    def test_a_system_cannot_report_for_another(self, test_client, test_db):
        """Otherwise anyone with any key could rewrite the fleet's inventory,
        and thereby influence what the hub is told to send."""
        victim_id, _ = register(test_client, "victim")
        _, attacker_key = register(test_client, "attacker")

        response = report(test_client, attacker_key, [payload(victim_id, "DATA1", 1)])

        assert response.status_code == status.HTTP_403_FORBIDDEN
        assert SnapshotRepository(test_db).get_by_system(victim_id, limit=None) == []

    def test_a_mixed_batch_is_rejected_outright(self, test_client, test_db):
        """One foreign row poisons the batch rather than being silently kept."""
        other_id, _ = register(test_client, "other")
        system_id, api_key = register(test_client, "reporter")

        response = report(
            test_client,
            api_key,
            [payload(system_id, "DATA1", 1), payload(other_id, "DATA1", 1)],
        )

        assert response.status_code == status.HTTP_403_FORBIDDEN
        assert SnapshotRepository(test_db).get_by_system(system_id, limit=None) == []


class TestFailuresAreReported:
    """Failures used to be collected, logged, and then dropped from the
    response -- callers got 201 and a shorter list with no way to tell which
    rows had been rejected.

    A row that fails *schema* validation is a 422 for the whole request. These
    cover the other case: a row that is well-formed but that the database
    refuses, which must not take the rest of the batch down with it.
    """

    @staticmethod
    def fail_on(monkeypatch, dataset: str) -> None:
        """Make the repository reject rows for one dataset."""
        from zfs_sync.database.repositories import SnapshotRepository

        original = SnapshotRepository.upsert

        def selective(self, **fields):
            if fields.get("dataset") == dataset:
                raise RuntimeError("disk full")
            return original(self, **fields)

        monkeypatch.setattr(SnapshotRepository, "upsert", selective)

    def test_a_rejected_row_is_named_in_the_response(
        self, test_client, test_db, monkeypatch
    ):
        system_id, api_key = register(test_client, "hub8")
        self.fail_on(monkeypatch, "DATA2")

        response = report(
            test_client,
            api_key,
            [payload(system_id, "DATA1", 1), payload(system_id, "DATA2", 2)],
        )

        assert response.status_code == status.HTTP_201_CREATED
        body = response.json()
        assert body["created"] == 1, "the good row still landed"
        assert len(body["failed"]) == 1
        failure = body["failed"][0]
        assert failure["dataset"] == "DATA2"
        assert "disk full" in failure["error"]

    def test_a_failed_row_does_not_put_its_dataset_in_scope(
        self, test_client, test_db, monkeypatch
    ):
        """A dataset whose rows all failed was not successfully reported, so
        its existing records must not be pruned on that basis."""
        system_id, api_key = register(test_client, "hub9")
        seed(test_client, api_key, system_id, datasets=("DATA1", "DATA2"))

        self.fail_on(monkeypatch, "DATA2")
        response = report(
            test_client,
            api_key,
            [payload(system_id, "DATA1", 1), payload(system_id, "DATA2", 9)],
        )

        assert response.json()["scope"] == ["pool1/DATA1"]
        remaining = SnapshotRepository(test_db).get_by_system(system_id, limit=None)
        assert len([s for s in remaining if s.dataset == "DATA2"]) == 3

    def test_a_malformed_row_rejects_the_whole_request(self, test_client):
        """Schema validation is all-or-nothing, and says which field."""
        system_id, api_key = register(test_client, "hub10")
        bad = payload(system_id, "DATA1", 1)
        bad["timestamp"] = None

        response = report(test_client, api_key, [bad])

        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY
        assert response.json()["error"]["code"] == "validation_error"


class TestDeletionIsOptIn:
    """Pruning happens only when the client says the report is complete.

    It used to happen on every batch, system-wide. The shipped reporting script
    chunks large inventories by row count, so on any fleet above the chunk size
    each chunk deleted what the previous one had just written -- leaving only
    the final chunk on record.
    """

    def test_a_plain_report_prunes_nothing(self, test_client, test_db):
        system_id, api_key = register(test_client, "optin1")
        seed(test_client, api_key, system_id, datasets=("DATA1",))

        response = report(test_client, api_key, [payload(system_id, "DATA1", 2)])

        assert response.json()["deleted"] == 0
        assert len(SnapshotRepository(test_db).get_by_system(system_id, limit=None)) == 3

    def test_chunked_reporting_does_not_destroy_earlier_chunks(
        self, test_client, test_db
    ):
        """The scenario the shipped script actually produces."""
        system_id, api_key = register(test_client, "optin2")
        every_day = [payload(system_id, "DATA1", day) for day in range(1, 11)]

        # Sent in three chunks, split by count as the script does.
        for start in (0, 4, 8):
            response = report(test_client, api_key, every_day[start : start + 4])
            assert response.status_code == status.HTTP_201_CREATED

        stored = SnapshotRepository(test_db).get_by_system(system_id, limit=None)
        assert len(stored) == 10, (
            "every chunk must survive; system-wide reconciliation left only the last"
        )

    def test_reconciling_a_partial_chunk_would_prune_within_its_dataset(
        self, test_client, test_db
    ):
        """Why a chunked client must not set reconcile.

        Scoping bounds deletion to the datasets in the batch, but a chunk that
        splits a dataset is still an incomplete report *of that dataset*. This
        documents the sharp edge the flag exists to avoid.
        """
        system_id, api_key = register(test_client, "optin3")
        every_day = [payload(system_id, "DATA1", day) for day in range(1, 11)]
        report(test_client, api_key, every_day)

        # A later chunk covering only part of DATA1, wrongly reconciling.
        report(test_client, api_key, every_day[:4], reconcile=True)

        stored = SnapshotRepository(test_db).get_by_system(system_id, limit=None)
        assert len(stored) == 4, (
            "reconcile means 'complete for these datasets'; misusing it prunes"
        )
