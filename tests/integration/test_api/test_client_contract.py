"""The API must keep returning exactly what the shipped client scripts read.

This test exists because its absence is precisely how `sync_executor.sh` came
to parse `.actions[]` from a response whose only payload key is `datasets` --
so it always logged "No sync actions required" and exited 0, having never
synced anything, for as long as it had existed. It also sent
`include_commands=true`, a parameter no endpoint has ever accepted, which
FastAPI silently ignored.

Every jq path the scripts use is asserted here. Drift now fails CI.
"""

import re
from datetime import datetime, timezone
from pathlib import Path
from typing import ClassVar

import pytest

from zfs_sync.database.repositories import (
    SnapshotRepository,
    SyncGroupRepository,
    SystemRepository,
)

TEMPLATES = Path(__file__).resolve().parents[3] / "docs" / "templates"
DATASET = "DATA1"


@pytest.fixture
def instruction(test_client, test_db):
    """A real instruction response for a hub with one lagging target."""
    systems = SystemRepository(test_db)
    groups = SyncGroupRepository(test_db)
    snapshots = SnapshotRepository(test_db)

    hub = systems.create(
        hostname="hub1", platform="linux", connectivity_status="online",
        ssh_hostname="hub1-san",
    )
    spoke = systems.create(
        hostname="spoke1", platform="linux", connectivity_status="online",
        ssh_hostname="spoke1-san", ssh_user="backup", ssh_port=2222,
    )
    for number in range(1, 21):
        snapshots.create(
            name=f"hubpool1/{DATASET}@2025-01-{number:02d}-000000",
            pool="hubpool1", dataset=DATASET, system_id=hub.id,
            timestamp=datetime(2025, 1, number, tzinfo=timezone.utc), size=1024,
        )
    for number in (1, 2):
        snapshots.create(
            name=f"spokepool1/{DATASET}@2025-01-{number:02d}-000000",
            pool="spokepool1", dataset=DATASET, system_id=spoke.id,
            timestamp=datetime(2025, 1, number, tzinfo=timezone.utc), size=1024,
        )

    group = groups.create(name="contract", directional=True, hub_system_id=hub.id)
    groups.add_system(group.id, hub.id)
    groups.add_system(group.id, spoke.id)

    payload = test_client.get(f"/api/v1/sync/instructions/{hub.id}").json()
    assert payload["dataset_count"] == 1, "fixture should produce one instruction"
    return payload


class TestInstructionFields:
    """Fields sync_executor.sh reads from each entry in .datasets[]."""

    REQUIRED: ClassVar[list] = [
        "dataset",
        "pool",
        "target_pool",
        "target_dataset",
        "starting_snapshot",
        "ending_snapshot",
        "target_ssh_hostname",
        "target_ssh_user",
        "target_ssh_port",
        "requires_rollback",
        "sync_group_id",
        "source_system_id",
        "target_system_id",
        "commands",
    ]

    def test_every_field_the_executor_reads_is_present(self, instruction):
        entry = instruction["datasets"][0]

        missing = [field for field in self.REQUIRED if field not in entry]
        assert not missing, f"sync_executor.sh reads fields the API does not return: {missing}"

    def test_the_payload_key_is_datasets_not_actions(self, instruction):
        assert "datasets" in instruction
        assert "actions" not in instruction, (
            "the executor parsed .actions[] for as long as it existed; "
            "if this key ever returns, fix the script rather than the test"
        )

    def test_the_target_identity_is_complete(self, instruction):
        entry = instruction["datasets"][0]

        assert entry["target_ssh_hostname"] == "spoke1-san"
        assert entry["target_ssh_user"] == "backup"
        assert entry["target_ssh_port"] == 2222

    def test_the_rendered_command_is_still_offered_for_dry_runs(self, instruction):
        commands = instruction["datasets"][0]["commands"]

        assert commands and commands[0].startswith("zfs send")

    def test_the_structured_fields_reconstruct_the_rendered_command(self, instruction):
        """What the script builds must match what the server rendered.

        The script does not eval the rendered string -- it rebuilds an argument
        vector -- so the two must not drift apart.
        """
        entry = instruction["datasets"][0]

        rebuilt = ["zfs", "send", "-c"]
        if entry["starting_snapshot"]:
            rebuilt += ["-I", f"{entry['pool']}/{entry['dataset']}@{entry['starting_snapshot']}"]
        rebuilt.append(f"{entry['pool']}/{entry['dataset']}@{entry['ending_snapshot']}")

        rendered_send = entry["commands"][0].split(" | ")[0]
        assert rendered_send == " ".join(rebuilt)


class TestDeclinedFields:
    """Fields the executor reads from .declined[] to explain a quiet run."""

    def test_declined_entries_carry_a_dataset_target_and_reason(
        self, test_client, test_db
    ):
        systems = SystemRepository(test_db)
        groups = SyncGroupRepository(test_db)
        snapshots = SnapshotRepository(test_db)

        hub = systems.create(
            hostname="hub-q", platform="linux", connectivity_status="online",
            ssh_hostname="hub-q-san",
        )
        spoke = systems.create(
            hostname="spoke-q", platform="linux", connectivity_status="online",
            ssh_hostname="spoke-q-san",
        )
        for system, pool in ((hub, "hubpool1"), (spoke, "spokepool1")):
            for number in range(1, 21):
                snapshots.create(
                    name=f"{pool}/{DATASET}@2025-01-{number:02d}-000000",
                    pool=pool, dataset=DATASET, system_id=system.id,
                    timestamp=datetime(2025, 1, number, tzinfo=timezone.utc), size=1024,
                )
        group = groups.create(name="quiet", directional=True, hub_system_id=hub.id)
        groups.add_system(group.id, hub.id)
        groups.add_system(group.id, spoke.id)

        payload = test_client.get(f"/api/v1/sync/instructions/{hub.id}").json()

        assert payload["dataset_count"] == 0
        entry = payload["declined"][0]
        for field in ("dataset", "target_hostname", "target_system_id", "reason"):
            assert field in entry, f"the executor reports '{field}' when nothing runs"
        assert entry["reason"]


class TestResultFields:
    """The payload sync_executor.sh posts back must be accepted."""

    def test_the_reported_outcome_is_accepted(self, test_client, instruction):
        entry = instruction["datasets"][0]

        response = test_client.post(
            "/api/v1/sync/results",
            json={
                "sync_group_id": entry["sync_group_id"],
                "dataset": entry["dataset"],
                "source_system_id": entry["source_system_id"],
                "target_system_id": entry["target_system_id"],
                "status": "success",
                "starting_snapshot": entry["starting_snapshot"],
                "ending_snapshot": entry["ending_snapshot"],
                "duration_seconds": 12,
                "error_message": None,
            },
        )

        assert response.status_code == 201, response.text


class TestShippedScriptsMatchTheApi:
    """The scripts themselves must not reference endpoints that do not exist."""

    SCRIPTS: ClassVar[list] = ["sync_executor.sh", "zfs_sync_client.sh", "zfs_sync_report.sh"]

    @pytest.mark.parametrize("script", SCRIPTS)
    def test_no_script_uses_the_phantom_include_commands_parameter(self, script):
        text = (TEMPLATES / script).read_text(encoding="utf-8")

        assert "include_commands" not in text, (
            f"{script} passes include_commands, which no endpoint accepts"
        )

    @pytest.mark.parametrize("script", SCRIPTS)
    def test_no_script_posts_to_the_nonexistent_register_route(self, script):
        text = (TEMPLATES / script).read_text(encoding="utf-8")

        assert "/systems/register" not in text, (
            f"{script} references POST /systems/register; the route is POST /systems"
        )

    @pytest.mark.parametrize("script", SCRIPTS)
    def test_every_api_path_a_script_uses_exists(self, script, test_client):
        """Catch endpoint drift in the scripts themselves."""
        from zfs_sync.api.app import app

        text = (TEMPLATES / script).read_text(encoding="utf-8")
        known = set(app.openapi()["paths"])

        used = set(re.findall(r"/api/v1/[A-Za-z0-9/_${}-]*", text))
        for path in used:
            # Normalise shell interpolation back to an OpenAPI parameter.
            normalised = re.sub(r"\$\{?[A-Za-z_][A-Za-z0-9_]*\}?", "{param}", path).rstrip("/")
            candidates = {
                re.sub(r"\{[^}]+\}", "{param}", candidate).rstrip("/") for candidate in known
            }
            assert normalised in candidates, (
                f"{script} calls {path}, which is not in the API: "
                f"normalised to {normalised}"
            )

    def test_the_executor_does_not_eval_server_supplied_text(self):
        """The command string is for display; execution uses an argv."""
        text = (TEMPLATES / "sync_executor.sh").read_text(encoding="utf-8")

        code = "\n".join(
            line for line in text.splitlines() if not line.strip().startswith("#")
        )
        assert "eval " not in code, (
            "sync_executor.sh must not eval strings returned by the API"
        )


class TestSnapshotBatchContract:
    """Fields the reporting scripts read from the batch response."""

    REQUIRED: ClassVar[list] = ["created", "updated", "deleted", "failed", "scope"]

    @staticmethod
    def register(test_client):
        response = test_client.post(
            "/api/v1/systems",
            json={"hostname": "reporter", "platform": "linux", "connectivity_status": "online"},
        )
        body = response.json()
        return body["id"], body["api_key"]

    def test_every_field_the_scripts_read_is_present(self, test_client):
        system_id, api_key = self.register(test_client)

        response = test_client.post(
            "/api/v1/snapshots/batch",
            headers={"X-API-Key": api_key},
            json=[
                {
                    "name": "pool1/DATA1@2025-01-01-000000",
                    "pool": "pool1",
                    "dataset": "DATA1",
                    "timestamp": datetime(2025, 1, 1, tzinfo=timezone.utc).isoformat(),
                    "size": 1024,
                    "system_id": system_id,
                }
            ],
        )

        body = response.json()
        missing = [field for field in self.REQUIRED if field not in body]
        assert not missing, f"reporting scripts read fields the API omits: {missing}"

    def test_the_reconcile_parameter_exists(self, test_client):
        """The scripts pass reconcile=true when sending a complete inventory.

        An unknown query parameter is silently ignored by FastAPI, which is how
        include_commands went unnoticed for so long -- so assert it is real.
        """
        from zfs_sync.api.app import app

        parameters = app.openapi()["paths"]["/api/v1/snapshots/batch"]["post"].get(
            "parameters", []
        )
        names = {p["name"] for p in parameters}
        assert "reconcile" in names, f"reconcile is not a real parameter; found {names}"

    @pytest.mark.parametrize("script", ["zfs_sync_client.sh", "zfs_sync_report.sh"])
    def test_reporting_scripts_reconcile_explicitly(self, script):
        """Both send complete inventories, so both must opt in -- otherwise
        retention pruning would never be reflected."""
        text = (TEMPLATES / script).read_text(encoding="utf-8")

        assert "reconcile=true" in text, (
            f"{script} reports a complete inventory but never asks to reconcile"
        )

    def test_the_report_script_chunks_by_dataset(self):
        """Chunking by row count splits a dataset across requests, which makes
        each request an incomplete report of it -- unsafe to reconcile."""
        text = (TEMPLATES / "zfs_sync_report.sh").read_text(encoding="utf-8")

        assert "select(.dataset == $ds)" in text, (
            "report script must group snapshots by dataset before sending"
        )
        assert "offset + chunk_size" not in text, (
            "report script still splits batches by row count"
        )
