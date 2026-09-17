"""Typed domain objects for sync planning.

The previous implementation passed ``Dict[str, Any]`` between four layers. That
is how ``hours_behind`` could be silently absent, and how the response key drift
between ``actions`` and ``datasets`` went unnoticed until a client script that
had never synced anything was read closely. Nothing here crosses a module
boundary as a bare dict.
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import List, Optional
from uuid import UUID


class SyncAction(str, Enum):
    """What the planner concluded for one (dataset, source, target) pair."""

    SYNC = "sync"
    SKIP = "skip"


class PlanReason(str, Enum):
    """Planner-level reasons, complementing the policy's DeclineReason.

    These describe conditions the pure policy cannot see because they concern
    systems and groups rather than snapshots.
    """

    # --- Group level: why a group produced no pairs at all. ---
    GROUP_DISABLED = "group_disabled"
    GROUP_NOT_DIRECTIONAL = "group_not_directional"
    #: Directional, but no hub is set. Distinct from the above because the fix
    #: differs: this group needs a hub chosen, not its mode changed. Groups
    #: created before the directional columns existed land here after the
    #: schema is recovered.
    GROUP_HUB_NOT_SET = "group_hub_not_set"
    GROUP_TOO_FEW_SYSTEMS = "group_too_few_systems"
    HUB_NOT_IN_GROUP = "hub_not_in_group"
    HUB_SYSTEM_MISSING = "hub_system_missing"

    # --- Pair level. ---
    #: The target has no ssh_hostname, so no command can be addressed to it.
    MISSING_SSH_IDENTITY = "missing_ssh_identity"
    #: The source's pool for this dataset could not be determined.
    SOURCE_POOL_UNKNOWN = "source_pool_unknown"
    #: The target holds snapshots the source does not, newer than the base.
    #: Reported alongside a sync, not instead of one: a backup target that has
    #: drifted must be rolled back to receive, which is what `zfs receive -F`
    #: does. Declining instead would mean such a pair never syncs at all --
    #: the same "nothing to sync" symptom with a better label.
    TARGET_DIVERGED = "target_diverged"


@dataclass(frozen=True)
class SystemRef:
    """The parts of a system the planner and renderer actually need."""

    id: UUID
    hostname: str
    ssh_hostname: Optional[str] = None
    ssh_user: Optional[str] = None
    ssh_port: int = 22

    @property
    def has_ssh_identity(self) -> bool:
        """True when a command can actually be addressed to this system."""
        return bool(self.ssh_hostname)


@dataclass(frozen=True)
class SyncDecision:
    """The planner's conclusion about one pair, whether or not it syncs.

    A decision is emitted for *every* pair considered. That is what makes
    suppression visible: an empty instruction list accompanied by a decision
    per pair explains itself, where the previous implementation returned an
    empty list whether the fleet was healthy or entirely filtered out.
    """

    sync_group_id: UUID
    dataset: str
    source: SystemRef
    target: SystemRef
    action: SyncAction
    reason: Optional[str] = None

    # Evidence -- populated wherever it is known, so an operator can see why.
    source_pool: Optional[str] = None
    target_pool: Optional[str] = None
    source_latest: Optional[str] = None
    target_latest: Optional[str] = None
    hours_behind: Optional[float] = None

    # The chosen window, present only when action is SYNC.
    starting_snapshot: Optional[str] = None
    ending_snapshot: Optional[str] = None
    ending_timestamp: Optional[datetime] = None
    full_send: bool = False
    #: The target holds snapshots the source lacks, newer than the base, so the
    #: receive needs -F to roll them back. Surfaced so an operator can see that
    #: local target snapshots are about to be discarded.
    requires_rollback: bool = False

    @property
    def is_sync(self) -> bool:
        return self.action is SyncAction.SYNC


@dataclass(frozen=True)
class SyncPlan:
    """Every decision for one sync group.

    ``skipped_reason`` is set when the group itself could not be planned (it is
    disabled, has too few systems, and so on), which is distinct from a group
    whose pairs were each individually declined.
    """

    sync_group_id: UUID
    decisions: List[SyncDecision] = field(default_factory=list)
    skipped_reason: Optional[str] = None

    @property
    def instructions(self) -> List[SyncDecision]:
        """Only the decisions that call for a sync."""
        return [decision for decision in self.decisions if decision.is_sync]

    @property
    def declined(self) -> List[SyncDecision]:
        """Only the decisions that do not."""
        return [decision for decision in self.decisions if not decision.is_sync]


class SyncGroupNotFound(LookupError):
    """Raised when a sync group does not exist.

    A typed domain error so routes can map it to 404 consistently. The previous
    service raised a bare ValueError, which one route caught and turned into a
    404 while two others let it surface as a 500 -- same condition, three
    behaviours.
    """

    def __init__(self, sync_group_id: UUID):
        self.sync_group_id = sync_group_id
        super().__init__(f"Sync group '{sync_group_id}' not found")
