"""The execution feedback loop, end to end through the API.

Instruction -> execution -> reported outcome -> visible state. Before this
existed the witness issued commands and never learned whether any of them
worked; the client template's reporting calls were commented out.
"""

from datetime import datetime, timezone

from fastapi import status

from zfs_sync.database.repositories import (
    SnapshotRepository,
    SyncGroupRepository,
    SystemRepository,
)

DATASET = "DATA1"


def build_fleet(db, spokes=("spoke1",)):
    systems = SystemRepository(db)
    groups = SyncGroupRepository(db)
    snapshots = SnapshotRepository(db)

    hub = systems.create(
        hostname="hub1", platform="linux", connectivity_status="online",
        ssh_hostname="hub1-san",
    )
    for number in range(1, 21):
        snapshots.create(
            name=f"hubpool1/{DATASET}@2025-01-{number:02d}-000000",
            pool="hubpool1", dataset=DATASET, system_id=hub.id,
            timestamp=datetime(2025, 1, number, tzinfo=timezone.utc), size=1024,
        )

    created = []
    for index, hostname in enumerate(spokes):
        pool = f"spokepool{index + 1}"
        spoke = systems.create(
            hostname=hostname, platform="linux", connectivity_status="online",
            ssh_hostname=f"{hostname}-san",
        )
        for number in (1, 2):
            snapshots.create(
                name=f"{pool}/{DATASET}@2025-01-{number:02d}-000000",
                pool=pool, dataset=DATASET, system_id=spoke.id,
                timestamp=datetime(2025, 1, number, tzinfo=timezone.utc), size=1024,
            )
        created.append(spoke)

    group = groups.create(name="results", directional=True, hub_system_id=hub.id)
    groups.add_system(group.id, hub.id)
    for spoke in created:
        groups.add_system(group.id, spoke.id)
    return group, hub, created


class TestReportingAnOutcome:
    def test_a_success_flips_the_pair_to_in_sync(self, auth_client, test_db):
        group, hub, (spoke,) = build_fleet(test_db)

        instructions = auth_client.get(f"/api/v1/sync/instructions/{hub.id}").json()
        assert instructions["dataset_count"] == 1
        entry = instructions["datasets"][0]

        response = auth_client.post(
            "/api/v1/sync/results",
            json={
                "sync_group_id": str(group.id),
                "dataset": entry["dataset"],
                "source_system_id": str(hub.id),
                "target_system_id": str(spoke.id),
                "status": "success",
                "starting_snapshot": entry["starting_snapshot"],
                "ending_snapshot": entry["ending_snapshot"],
                "bytes_transferred": 4096,
            },
        )

        assert response.status_code == status.HTTP_201_CREATED
        assert response.json()["status"] == "success"

        summary = auth_client.get(f"/api/v1/sync/groups/{group.id}/status").json()
        assert summary["in_sync_count"] == 1
        assert summary["total_states"] == 1

    def test_a_failure_is_visible_with_its_message(self, auth_client, test_db):
        group, hub, (spoke,) = build_fleet(test_db)

        auth_client.post(
            "/api/v1/sync/results",
            json={
                "sync_group_id": str(group.id),
                "dataset": DATASET,
                "source_system_id": str(hub.id),
                "target_system_id": str(spoke.id),
                "status": "failed",
                "error_message": "cannot receive incremental stream: destination modified",
            },
        )

        summary = auth_client.get(f"/api/v1/sync/groups/{group.id}/status").json()
        assert summary["error_count"] == 1

        states = auth_client.get(f"/api/v1/sync/groups/{group.id}/states").json()
        assert "destination modified" in states[0]["error_message"]

    def test_history_records_every_attempt(self, auth_client, test_db):
        group, hub, (spoke,) = build_fleet(test_db)

        for attempt_status, message in (("failed", "timeout"), ("success", None)):
            auth_client.post(
                "/api/v1/sync/results",
                json={
                    "sync_group_id": str(group.id),
                    "dataset": DATASET,
                    "source_system_id": str(hub.id),
                    "target_system_id": str(spoke.id),
                    "status": attempt_status,
                    "error_message": message,
                },
            )

        runs = auth_client.get(f"/api/v1/sync/groups/{group.id}/runs").json()
        assert runs["run_count"] == 2
        assert {run["status"] for run in runs["runs"]} == {"failed", "success"}

        # The projection shows the latest verdict, history keeps both.
        summary = auth_client.get(f"/api/v1/sync/groups/{group.id}/status").json()
        assert summary["in_sync_count"] == 1
        assert summary["error_count"] == 0

    def test_each_target_is_tracked_independently(self, auth_client, test_db):
        group, hub, spokes = build_fleet(test_db, spokes=("spoke1", "spoke2"))

        auth_client.post(
            "/api/v1/sync/results",
            json={
                "sync_group_id": str(group.id), "dataset": DATASET,
                "source_system_id": str(hub.id), "target_system_id": str(spokes[0].id),
                "status": "success",
            },
        )
        auth_client.post(
            "/api/v1/sync/results",
            json={
                "sync_group_id": str(group.id), "dataset": DATASET,
                "source_system_id": str(hub.id), "target_system_id": str(spokes[1].id),
                "status": "failed", "error_message": "unreachable",
            },
        )

        summary = auth_client.get(f"/api/v1/sync/groups/{group.id}/status").json()
        assert summary["in_sync_count"] == 1
        assert summary["error_count"] == 1
        assert summary["total_states"] == 2


class TestRejectedReports:
    def test_an_unknown_status_is_rejected(self, auth_client, test_db):
        group, hub, (spoke,) = build_fleet(test_db)

        response = auth_client.post(
            "/api/v1/sync/results",
            json={
                "sync_group_id": str(group.id), "dataset": DATASET,
                "source_system_id": str(hub.id), "target_system_id": str(spoke.id),
                "status": "probably-fine",
            },
        )

        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY
        assert response.json()["error"]["code"] == "validation_error"

    def test_a_negative_byte_count_is_rejected(self, auth_client, test_db):
        group, hub, (spoke,) = build_fleet(test_db)

        response = auth_client.post(
            "/api/v1/sync/results",
            json={
                "sync_group_id": str(group.id), "dataset": DATASET,
                "source_system_id": str(hub.id), "target_system_id": str(spoke.id),
                "status": "success", "bytes_transferred": -1,
            },
        )

        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY


class TestTheLoopIsClosed:
    def test_instruction_then_report_then_no_further_instruction(
        self, auth_client, test_db
    ):
        """After a successful sync is reported and the target catches up, the
        hub is no longer told to sync it -- and the response says why."""
        group, hub, (spoke,) = build_fleet(test_db)
        snapshots = SnapshotRepository(test_db)

        before = auth_client.get(f"/api/v1/sync/instructions/{hub.id}").json()
        assert before["dataset_count"] == 1
        entry = before["datasets"][0]

        # The client runs it, the target gains the snapshots, and it reports back.
        for number in range(3, 21):
            snapshots.create(
                name=f"spokepool1/{DATASET}@2025-01-{number:02d}-000000",
                pool="spokepool1", dataset=DATASET, system_id=spoke.id,
                timestamp=datetime(2025, 1, number, tzinfo=timezone.utc), size=1024,
            )
        auth_client.post(
            "/api/v1/sync/results",
            json={
                "sync_group_id": str(group.id), "dataset": DATASET,
                "source_system_id": str(hub.id), "target_system_id": str(spoke.id),
                "status": "success",
                "starting_snapshot": entry["starting_snapshot"],
                "ending_snapshot": entry["ending_snapshot"],
            },
        )

        after = auth_client.get(f"/api/v1/sync/instructions/{hub.id}").json()

        assert after["dataset_count"] == 0
        assert len(after["declined"]) == 1
        assert after["declined"][0]["reason"] == "base_equals_end"
        assert after["declined"][0]["hours_behind"] == 0.0
