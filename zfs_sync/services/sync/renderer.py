"""Renders a :class:`SyncDecision` into a ``zfs send | ssh zfs receive`` command.

This is the only stage that builds command strings, and it works from a typed
decision rather than a dict of loosely-related fields.

Two problems in the code this replaces:

``SSHCommandGenerator`` carried two parallel command builders -- a pull-shaped
pair (``generate_zfs_send_command`` / ``generate_zfs_receive_command``) that
correctly handled ``ssh_user`` and ``ssh_port``, and a push-shaped pair that the
service actually called and that hardcoded ``ssh {hostname}``. So the builder
which understood SSH identity was the one nothing used, and any target on a
non-default port or requiring a username got a command that could not work.

Dataset paths were resolved by seven scattered ``if "/" in dataset`` checks.
That heuristic drops the pool for a nested dataset reported without its pool
prefix (``data/sub`` under pool ``tank`` rendered as ``data/sub``, not
``tank/data/sub``). Resolution happens once here instead.
"""

import shlex
from typing import List, Optional

from zfs_sync.services.sync.types import SyncAction, SyncDecision


class CommandRenderError(ValueError):
    """Raised when a decision cannot be rendered into a runnable command.

    The planner should already have declined such pairs; reaching the renderer
    means something upstream let an unrunnable decision through, and failing
    loudly beats emitting ``ssh None`` or a reversed stream.
    """


def quote(value: str) -> str:
    """Quote a value for safe use in a shell command.

    ``shlex.quote`` leaves ordinary values untouched -- letters, digits and
    ``@ % + = : , . / -`` are all safe -- and only quotes what would otherwise
    break out of the command.
    """
    return shlex.quote(value)


def dataset_path(pool: str, dataset: str) -> str:
    """Return the fully qualified ``pool/dataset`` path.

    Clients report ``dataset`` inconsistently: sometimes bare (``DATA1``),
    sometimes already pool-prefixed (``tank/DATA1``). Both must resolve to the
    same path, and a nested dataset must keep its pool.
    """
    if not pool:
        raise CommandRenderError(f"No pool known for dataset {dataset!r}")
    prefix = f"{pool}/"
    if dataset == pool or dataset.startswith(prefix):
        # Already fully qualified.
        return dataset
    return f"{pool}/{dataset}"


def ssh_target(hostname: str, user: Optional[str] = None) -> str:
    """Build the ``user@host`` portion of an ssh invocation."""
    return f"{user}@{hostname}" if user else hostname


def ssh_prefix(hostname: str, user: Optional[str] = None, port: int = 22) -> List[str]:
    """Build the ssh command and its options, as argv pieces."""
    parts = ["ssh"]
    if port and port != 22:
        parts += ["-p", str(port)]
    parts.append(quote(ssh_target(hostname, user)))
    return parts


def render_sync_command(
    decision: SyncDecision,
    *,
    compressed: bool = True,
    resumable: bool = True,
    force_rollback: Optional[bool] = None,
) -> str:
    """Render the command that performs ``decision``.

    The command runs on the *source* system: it sends from the source's pool
    and pipes into ``zfs receive`` on the target over ssh.

    Args:
        decision: A decision whose action is SYNC.
        compressed: Pass ``-c`` to ``zfs send`` (send already-compressed blocks).
        resumable: Pass ``-s`` to ``zfs receive`` (allow a resume token).
        force_rollback: Pass ``-F`` to ``zfs receive``, discarding target
            snapshots taken since the base. Defaults to the decision's
            ``requires_rollback``, which the planner sets only when the target
            has actually drifted; pass False to refuse the rollback instead.

    Raises:
        CommandRenderError: If the decision is not renderable.
    """
    if decision.action is not SyncAction.SYNC:
        raise CommandRenderError(
            f"Decision for {decision.dataset} is {decision.action.value}, not a sync"
        )

    if not decision.ending_snapshot:
        raise CommandRenderError(f"No ending snapshot for dataset {decision.dataset!r}")

    if not decision.target.has_ssh_identity:
        raise CommandRenderError(
            f"Target {decision.target.hostname!r} has no ssh_hostname; "
            "no command can be addressed to it"
        )

    if decision.starting_snapshot == decision.ending_snapshot:
        raise CommandRenderError(
            f"Starting and ending snapshot are both {decision.ending_snapshot!r}; "
            "there is nothing to send"
        )

    if not decision.source_pool:
        raise CommandRenderError(f"No source pool known for dataset {decision.dataset!r}")

    source_path = dataset_path(decision.source_pool, decision.dataset)
    # A target that has never held this dataset has no pool of its own yet;
    # mirroring the source's pool name is the only sensible default.
    target_path = dataset_path(decision.target_pool or decision.source_pool, decision.dataset)

    send = ["zfs", "send"]
    if compressed:
        send.append("-c")
    if decision.starting_snapshot:
        # -I sends the base and every intermediate snapshot up to the end.
        # Order matters: base first, end second.
        send += ["-I", quote(f"{source_path}@{decision.starting_snapshot}")]
    send.append(quote(f"{source_path}@{decision.ending_snapshot}"))

    rollback = decision.requires_rollback if force_rollback is None else force_rollback

    receive = ["zfs", "receive"]
    if rollback:
        receive.append("-F")
    if resumable:
        receive.append("-s")
    receive.append(quote(target_path))

    remote = ssh_prefix(
        hostname=decision.target.ssh_hostname,
        user=decision.target.ssh_user,
        port=decision.target.ssh_port,
    )
    remote.append(quote(" ".join(receive)))

    return f"{' '.join(send)} | {' '.join(remote)}"


__all__ = [
    "CommandRenderError",
    "dataset_path",
    "render_sync_command",
    "ssh_prefix",
    "ssh_target",
]
