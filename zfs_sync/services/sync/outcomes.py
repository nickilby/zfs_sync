"""Recording what happened when a client executed a sync instruction.

This closes the loop. Until now the witness issued commands and never learned
whether any of them worked: the client template's reporting calls were
commented out, and the only trace of an execution was whatever the operator saw
in their own shell.

Two things are written for each reported outcome:

* a ``sync_runs`` row -- append-only history, so there is an audit trail;
* the ``sync_states`` projection -- current status, which is what the dashboard
  and the status summary read.
"""

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional
from uuid import UUID

from sqlalchemy.orm import Session

from zfs_sync.database.models import SyncRunModel
from zfs_sync.database.repositories import SyncRunRepository
from zfs_sync.enums import SyncStatus
from zfs_sync.logging_config import get_logger
from zfs_sync.services.sync.state import SyncStateService
from zfs_sync.services.sync.types import SyncDecision

logger = get_logger(__name__)


class RunStatus(str, Enum):
    """How a reported execution ended."""

    SUCCESS = "success"
    FAILED = "failed"
    STARTED = "started"

    @property
    def sync_status(self) -> SyncStatus:
        """The projected state this outcome implies."""
        return {
            RunStatus.SUCCESS: SyncStatus.IN_SYNC,
            RunStatus.FAILED: SyncStatus.ERROR,
            RunStatus.STARTED: SyncStatus.SYNCING,
        }[self]


@dataclass(frozen=True)
class SyncOutcome:
    """A client's report of one execution attempt."""

    sync_group_id: UUID
    dataset: str
    source_system_id: UUID
    target_system_id: UUID
    status: RunStatus
    starting_snapshot: Optional[str] = None
    ending_snapshot: Optional[str] = None
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    duration_seconds: Optional[int] = None
    bytes_transferred: Optional[int] = None
    error_message: Optional[str] = None
    reported_by_system_id: Optional[UUID] = None


class SyncOutcomeService:
    """Persists reported outcomes and projects them into sync state."""

    def __init__(self, db: Session):
        self.db = db
        self.run_repo = SyncRunRepository(db)
        self.state_service = SyncStateService(db)

    def record(self, outcome: SyncOutcome) -> SyncRunModel:
        """Record one outcome and update the state it implies.

        The state row is keyed on the *target*: it is the target that is or is
        not in sync, and a hub pushing to three spokes has three independent
        states rather than one shared verdict.
        """
        run = self.run_repo.create(
            sync_group_id=outcome.sync_group_id,
            dataset=outcome.dataset,
            source_system_id=outcome.source_system_id,
            target_system_id=outcome.target_system_id,
            starting_snapshot=outcome.starting_snapshot,
            ending_snapshot=outcome.ending_snapshot,
            status=outcome.status.value,
            started_at=outcome.started_at,
            finished_at=outcome.finished_at or datetime.now(timezone.utc),
            duration_seconds=outcome.duration_seconds,
            bytes_transferred=outcome.bytes_transferred,
            error_message=outcome.error_message,
            reported_by_system_id=outcome.reported_by_system_id,
        )

        self.state_service.update_sync_state(
            sync_group_id=outcome.sync_group_id,
            dataset=outcome.dataset,
            system_id=outcome.target_system_id,
            status=outcome.status.sync_status,
            error_message=outcome.error_message,
        )

        log = logger.warning if outcome.status is RunStatus.FAILED else logger.info
        log(
            "Sync %s: %s -> %s [%s] %s..%s%s",
            outcome.status.value,
            outcome.source_system_id,
            outcome.target_system_id,
            outcome.dataset,
            outcome.starting_snapshot or "(full)",
            outcome.ending_snapshot,
            f": {outcome.error_message}" if outcome.error_message else "",
        )
        return run

    def record_planned_states(self, decisions: List[SyncDecision]) -> int:
        """Project planning decisions into ``sync_states``.

        Called by the scheduler so that a pair the planner has evaluated shows
        its standing even before any client reports an execution. Previously
        the scheduler discarded its planning results entirely while claiming in
        a docstring to update state, so ``sync_states`` was only ever written
        by conflict resolution -- meaning the dashboard showed conflicts and
        nothing else.

        Pairs already reported as syncing are left alone, so a run in progress
        is not overwritten by a plan that predates it.
        """
        updated = 0
        for decision in decisions:
            status = SyncStatus.OUT_OF_SYNC if decision.is_sync else SyncStatus.IN_SYNC

            existing = self.state_service.sync_state_repo.get_by_dataset(
                sync_group_id=decision.sync_group_id,
                dataset=decision.dataset,
                system_id=decision.target.id,
            )
            if existing is not None and existing.status == SyncStatus.SYNCING.value:
                continue

            self.state_service.update_sync_state(
                sync_group_id=decision.sync_group_id,
                dataset=decision.dataset,
                system_id=decision.target.id,
                status=status,
                error_message=None if decision.is_sync else decision.reason,
            )
            updated += 1
        return updated

    def recent_runs(self, sync_group_id: UUID, limit: int = 50) -> List[Dict[str, Any]]:
        """Recent runs for a sync group, newest first, as plain dicts."""
        return [
            {
                "id": str(run.id),
                "dataset": run.dataset,
                "source_system_id": str(run.source_system_id),
                "target_system_id": str(run.target_system_id),
                "starting_snapshot": run.starting_snapshot,
                "ending_snapshot": run.ending_snapshot,
                "status": run.status,
                "started_at": run.started_at.isoformat() if run.started_at else None,
                "finished_at": run.finished_at.isoformat() if run.finished_at else None,
                "duration_seconds": run.duration_seconds,
                "bytes_transferred": run.bytes_transferred,
                "error_message": run.error_message,
            }
            for run in self.run_repo.get_for_sync_group(sync_group_id, limit=limit)
        ]


__all__ = ["RunStatus", "SyncOutcome", "SyncOutcomeService"]
