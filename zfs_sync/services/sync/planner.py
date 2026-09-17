"""Sync planner: turns stored snapshot state into per-pair decisions.

This is the only stage that touches the database. It enumerates every
``(dataset, source, target)`` pair in a sync group, hands each one to the pure
policy, and returns a :class:`SyncDecision` for all of them -- including the
pairs it declines.

Two things differ from the coordination service this replaces.

The unit of work is the pair, not the dataset. The old implementation
consolidated instructions keyed on dataset alone, so when one hub dataset was
behind on two spokes the second spoke's SSH host and pool were discarded. Only
the hub can execute these commands (they send from the hub's pool), so the
effect was that the one host able to perform the sync was told about a single
target while the other's command went only to a machine that could not run it.

Snapshots are loaded once per group rather than per dataset per system.
"""

from collections import defaultdict
from datetime import datetime, timezone
from typing import Dict, List, Optional, Sequence, Tuple
from uuid import UUID

from sqlalchemy.orm import Session

from zfs_sync.config import get_settings
from zfs_sync.database.repositories import (
    SnapshotRepository,
    SyncGroupRepository,
    SystemRepository,
)
from zfs_sync.logging_config import get_logger
from zfs_sync.services.sync.policy import (
    Snapshot,
    choose_send_window,
    latest_anchor,
    naming_from_pattern,
    normalize_to_utc,
)
from zfs_sync.services.sync.types import (
    PlanReason,
    SyncAction,
    SyncDecision,
    SyncGroupNotFound,
    SyncPlan,
    SystemRef,
)

logger = get_logger(__name__)


def extract_snapshot_name(full_name: str) -> str:
    """Return the snapshot name without its ``pool/dataset@`` prefix."""
    if "@" in full_name:
        return full_name.rsplit("@", 1)[-1]
    return full_name


class SyncPlanner:
    """Plans snapshot synchronisation for directional sync groups."""

    def __init__(self, db: Session, settings=None):
        self.db = db
        self.settings = settings if settings is not None else get_settings()
        self.sync_group_repo = SyncGroupRepository(db)
        self.system_repo = SystemRepository(db)
        self.snapshot_repo = SnapshotRepository(db)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def plan_group(self, sync_group_id: UUID, now: Optional[datetime] = None) -> SyncPlan:
        """Produce a decision for every pair in ``sync_group_id``.

        Args:
            sync_group_id: The group to plan.
            now: Reference time; defaults to the current UTC time. Injected so
                planning is reproducible under test.

        Raises:
            SyncGroupNotFound: If no such group exists.
        """
        sync_group = self.sync_group_repo.get(sync_group_id)
        if not sync_group:
            raise SyncGroupNotFound(sync_group_id)

        reference = normalize_to_utc(now) if now else datetime.now(timezone.utc)

        skipped = self._group_level_skip(sync_group)
        if skipped is not None:
            logger.debug("Sync group %s not planned: %s", sync_group_id, skipped.value)
            return SyncPlan(sync_group_id=sync_group_id, skipped_reason=skipped.value)

        hub_id = sync_group.hub_system_id
        system_ids = [assoc.system_id for assoc in sync_group.system_associations]
        target_ids = [sid for sid in system_ids if sid != hub_id]

        systems = self._load_systems(system_ids)
        hub = systems.get(hub_id)
        if hub is None:
            return SyncPlan(
                sync_group_id=sync_group_id,
                skipped_reason=PlanReason.HUB_SYSTEM_MISSING.value,
            )

        # One query for the whole group, indexed in memory thereafter.
        inventory = self._load_inventory(system_ids)

        decisions: List[SyncDecision] = []
        for dataset in sorted(self._datasets_in(inventory)):
            hub_snapshots = inventory.get((hub_id, dataset), [])
            if not hub_snapshots:
                # The hub holds nothing for this dataset, so it cannot be the
                # source of truth for it. Not a per-target failure.
                continue

            for target_id in target_ids:
                target = systems.get(target_id)
                if target is None:
                    continue
                decisions.append(
                    self._decide(
                        sync_group_id=sync_group_id,
                        dataset=dataset,
                        source=hub,
                        target=target,
                        source_snapshots=hub_snapshots,
                        target_snapshots=inventory.get((target_id, dataset), []),
                        now=reference,
                    )
                )

        logger.info(
            "Planned sync group %s: %d pair(s), %d to sync",
            sync_group_id,
            len(decisions),
            sum(1 for decision in decisions if decision.is_sync),
        )
        return SyncPlan(sync_group_id=sync_group_id, decisions=decisions)

    def plan_for_system(
        self,
        system_id: UUID,
        sync_group_id: Optional[UUID] = None,
        now: Optional[datetime] = None,
    ) -> List[SyncDecision]:
        """Return the decisions a given system is responsible for executing.

        Commands send *from* the source's pool, so only the source can run
        them. A system therefore receives the pairs where it is the source --
        which for a directional group means the hub receives every target's
        instruction, rather than one of them.
        """
        if sync_group_id is not None:
            groups = [self.sync_group_repo.get(sync_group_id)]
            if groups[0] is None:
                raise SyncGroupNotFound(sync_group_id)
        else:
            groups = [
                group
                for group in self.sync_group_repo.get_all()
                if group.enabled
                and any(assoc.system_id == system_id for assoc in group.system_associations)
            ]

        decisions: List[SyncDecision] = []
        for group in groups:
            if group is None:
                continue
            plan = self.plan_group(group.id, now=now)
            decisions.extend(
                decision for decision in plan.decisions if decision.source.id == system_id
            )
        return decisions

    def dataset_pools(
        self, system_ids: Sequence[UUID]
    ) -> Dict[str, List[Tuple[str, UUID]]]:
        """Map each dataset name to the ``(pool, system_id)`` pairs holding it.

        Replaces ``sync_queries.get_datasets_for_systems``, which paged through
        ``get_by_system`` and so silently saw only each system's newest 100
        snapshots -- on a real fleet, datasets whose recent snapshots fell
        outside that page were invisible to conflict detection entirely.
        """
        mapping: Dict[str, List[Tuple[str, UUID]]] = defaultdict(list)
        for row in self.snapshot_repo.get_for_systems(system_ids):
            entry = (row.pool, row.system_id)
            if entry not in mapping[row.dataset]:
                mapping[row.dataset].append(entry)
        return dict(mapping)

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _group_level_skip(self, sync_group) -> Optional[PlanReason]:
        """Return why the group cannot be planned at all, or None."""
        if not sync_group.enabled:
            return PlanReason.GROUP_DISABLED

        if not sync_group.directional:
            # Bidirectional planning has never been reachable: the previous
            # implementation returned early here too, leaving ~70 lines of
            # bidirectional branching downstream that could never execute.
            return PlanReason.GROUP_NOT_DIRECTIONAL

        if not sync_group.hub_system_id:
            # Reported separately because the remedy differs: this group needs
            # a hub selected, not its mode changed.
            return PlanReason.GROUP_HUB_NOT_SET

        system_ids = [assoc.system_id for assoc in sync_group.system_associations]
        if len(system_ids) < 2:
            return PlanReason.GROUP_TOO_FEW_SYSTEMS

        if sync_group.hub_system_id not in system_ids:
            return PlanReason.HUB_NOT_IN_GROUP

        return None

    def _load_systems(self, system_ids: Sequence[UUID]) -> Dict[UUID, SystemRef]:
        systems: Dict[UUID, SystemRef] = {}
        for system_id in system_ids:
            row = self.system_repo.get(system_id)
            if row is None:
                continue
            systems[system_id] = SystemRef(
                id=row.id,
                hostname=row.hostname,
                ssh_hostname=row.ssh_hostname,
                ssh_user=row.ssh_user,
                ssh_port=row.ssh_port if row.ssh_port else 22,
            )
        return systems

    def _load_inventory(
        self, system_ids: Sequence[UUID]
    ) -> Dict[Tuple[UUID, str], List[Tuple[str, datetime, str]]]:
        """Index every snapshot in the group by ``(system_id, dataset)``.

        Values are ``(name, timestamp, pool)`` triples: the policy needs the
        first two, and the renderer needs the pool.
        """
        index: Dict[Tuple[UUID, str], List[Tuple[str, datetime, str]]] = defaultdict(list)
        for row in self.snapshot_repo.get_for_systems(system_ids):
            index[(row.system_id, row.dataset)].append(
                (extract_snapshot_name(row.name), normalize_to_utc(row.timestamp), row.pool)
            )
        return index

    @staticmethod
    def _datasets_in(inventory: Dict[Tuple[UUID, str], List]) -> set:
        return {dataset for _, dataset in inventory}

    @staticmethod
    def _as_snapshots(rows: Sequence[Tuple[str, datetime, str]]) -> List[Snapshot]:
        return [(name, timestamp) for name, timestamp, _ in rows]

    @staticmethod
    def _pool_of(rows: Sequence[Tuple[str, datetime, str]]) -> Optional[str]:
        """Return the pool holding this dataset, newest snapshot first.

        Taking the newest rather than an arbitrary row matters when a dataset
        has been moved between pools: the current location is the one that can
        actually send or receive.
        """
        if not rows:
            return None
        return max(rows, key=lambda row: row[1])[2]

    def _decide(
        self,
        sync_group_id: UUID,
        dataset: str,
        source: SystemRef,
        target: SystemRef,
        source_snapshots: Sequence[Tuple[str, datetime, str]],
        target_snapshots: Sequence[Tuple[str, datetime, str]],
        now: datetime,
    ) -> SyncDecision:
        """Evaluate a single (dataset, source, target) pair."""
        naming = naming_from_pattern(self.settings.snapshot_anchor_pattern)
        source_pairs = self._as_snapshots(source_snapshots)
        target_pairs = self._as_snapshots(target_snapshots)

        source_pool = self._pool_of(source_snapshots)
        target_pool = self._pool_of(target_snapshots)

        source_anchor = latest_anchor(source_pairs, naming)
        target_anchor = latest_anchor(target_pairs, naming)
        source_latest = source_anchor[0] if source_anchor else None
        target_latest = target_anchor[0] if target_anchor else None

        hours_behind: Optional[float] = None
        if source_anchor and target_anchor:
            hours_behind = (source_anchor[1] - target_anchor[1]).total_seconds() / 3600

        def decision(action: SyncAction, reason: Optional[str], **extra) -> SyncDecision:
            return SyncDecision(
                sync_group_id=sync_group_id,
                dataset=dataset,
                source=source,
                target=target,
                action=action,
                reason=reason,
                source_pool=source_pool,
                target_pool=target_pool,
                source_latest=source_latest,
                target_latest=target_latest,
                hours_behind=hours_behind,
                **extra,
            )

        result = choose_send_window(
            source=source_pairs,
            target=target_pairs,
            now=now,
            min_age_hours=self.settings.snapshot_min_age_hours,
            min_gap_hours=self.settings.snapshot_min_gap_hours,
            naming=naming,
        )

        if not result.ok:
            reason = result.reason.value if result.reason else None
            return decision(SyncAction.SKIP, reason)

        window = result.window

        # A target holding snapshots the source lacks, newer than the base,
        # cannot receive an incremental stream as-is -- the receive needs -F to
        # roll them back first. That is reported rather than refused: declining
        # would mean a drifted backup target never syncs again, which is the
        # state this fleet was already in.
        diverged = self._diverged_after(source_pairs, target_pairs, window.base_timestamp)

        if not target.has_ssh_identity:
            # The previous implementation appended an action with
            # sync_command=None here and said nothing.
            return decision(SyncAction.SKIP, PlanReason.MISSING_SSH_IDENTITY.value)

        if not source_pool:
            return decision(SyncAction.SKIP, PlanReason.SOURCE_POOL_UNKNOWN.value)

        reason = result.reason.value if result.reason else None
        if diverged:
            reason = PlanReason.TARGET_DIVERGED.value

        return decision(
            SyncAction.SYNC,
            reason,
            starting_snapshot=window.base,
            ending_snapshot=window.end,
            ending_timestamp=window.end_timestamp,
            full_send=window.full_send,
            requires_rollback=diverged,
        )

    @staticmethod
    def _diverged_after(
        source: Sequence[Snapshot],
        target: Sequence[Snapshot],
        after: Optional[datetime],
    ) -> bool:
        """True when the target has its own snapshots newer than ``after``.

        Snapshots older than the incremental base do not block a receive, so
        only later ones count. With no base (a full send) nothing is blocking.
        """
        if after is None:
            return False
        source_names = {name for name, _ in source}
        return any(
            name not in source_names and timestamp > after for name, timestamp in target
        )


__all__ = [
    "SyncPlanner",
    "extract_snapshot_name",
]
