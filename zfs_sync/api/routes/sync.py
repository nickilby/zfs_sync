"""Synchronization coordination endpoints."""

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from zfs_sync.api.schemas.sync import (
    DatasetSyncInstruction,
    DeclinedPair,
    SyncInstructionsResponse,
    SyncResultCreate,
    SyncResultResponse,
    SyncStateResponse,
    SyncStatusSummary,
)
from zfs_sync.database import get_db
from zfs_sync.database.repositories import SyncStateRepository
from zfs_sync.enums import SyncStatus
from zfs_sync.logging_config import get_logger
from zfs_sync.services.sync.outcomes import RunStatus, SyncOutcome, SyncOutcomeService
from zfs_sync.services.sync.planner import SyncPlanner
from zfs_sync.services.sync.renderer import CommandRenderError, render_sync_command
from zfs_sync.services.sync.state import SyncStateService
from zfs_sync.services.sync.types import SyncDecision

logger = get_logger(__name__)
router = APIRouter()


def _as_instruction(decision: SyncDecision) -> Optional[DatasetSyncInstruction]:
    """Render one decision into a client-facing instruction."""
    try:
        command = render_sync_command(decision)
    except CommandRenderError as exc:
        # The planner declines unrenderable pairs, so this is unexpected --
        # report it rather than returning an instruction with no command.
        logger.warning(
            "Skipping instruction for %s -> %s: %s",
            decision.dataset,
            decision.target.hostname,
            exc,
        )
        return None

    return DatasetSyncInstruction(
        pool=decision.source_pool,
        dataset=decision.dataset,
        target_pool=decision.target_pool or decision.source_pool,
        target_dataset=decision.dataset,
        starting_snapshot=decision.starting_snapshot,
        ending_snapshot=decision.ending_snapshot,
        source_ssh_hostname=decision.source.ssh_hostname,
        target_ssh_hostname=decision.target.ssh_hostname,
        target_ssh_user=decision.target.ssh_user,
        target_ssh_port=decision.target.ssh_port,
        source_system_id=str(decision.source.id),
        target_system_id=str(decision.target.id),
        sync_group_id=str(decision.sync_group_id),
        requires_rollback=decision.requires_rollback,
        commands=[command],
    )


def _as_declined(decision: SyncDecision) -> DeclinedPair:
    return DeclinedPair(
        dataset=decision.dataset,
        target_system_id=str(decision.target.id),
        target_hostname=decision.target.hostname,
        reason=decision.reason,
        source_latest=decision.source_latest,
        target_latest=decision.target_latest,
        hours_behind=decision.hours_behind,
    )


@router.get("/sync/states", response_model=List[SyncStateResponse])
async def list_sync_states(skip: int = 0, limit: int = 100, db: Session = Depends(get_db)):
    """List all synchronization states."""
    repo = SyncStateRepository(db)
    states = repo.get_all(skip=skip, limit=limit)
    return [SyncStateResponse.model_validate(s) for s in states]


@router.get("/sync/states/{state_id}", response_model=SyncStateResponse)
async def get_sync_state(state_id: UUID, db: Session = Depends(get_db)):
    """Get a sync state by ID."""
    repo = SyncStateRepository(db)
    state = repo.get(state_id)
    if not state:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Sync state not found")
    return SyncStateResponse.model_validate(state)


@router.get("/sync/groups/{group_id}/states", response_model=List[SyncStateResponse])
async def get_sync_states_by_group(group_id: UUID, db: Session = Depends(get_db)):
    """Get all sync states for a sync group."""
    repo = SyncStateRepository(db)
    states = repo.get_by_sync_group(group_id)
    return [SyncStateResponse.model_validate(s) for s in states]


@router.get("/sync/groups/{group_id}/decisions")
async def get_sync_decisions(group_id: UUID, db: Session = Depends(get_db)) -> Dict[str, Any]:
    """Every planning decision for a sync group, actioned or not.

    Replaces the previous `/mismatches` and `/actions` pair, which reported
    only part of the picture and disagreed with each other about what a
    missing sync group meant.
    """
    plan = SyncPlanner(db).plan_group(group_id)
    return {
        "sync_group_id": str(group_id),
        "skipped_reason": plan.skipped_reason,
        "decision_count": len(plan.decisions),
        "sync_count": len(plan.instructions),
        "decisions": [
            {
                "dataset": decision.dataset,
                "action": decision.action.value,
                "reason": decision.reason,
                "source_system_id": str(decision.source.id),
                "source_hostname": decision.source.hostname,
                "target_system_id": str(decision.target.id),
                "target_hostname": decision.target.hostname,
                "source_pool": decision.source_pool,
                "target_pool": decision.target_pool,
                "source_latest": decision.source_latest,
                "target_latest": decision.target_latest,
                "hours_behind": decision.hours_behind,
                "starting_snapshot": decision.starting_snapshot,
                "ending_snapshot": decision.ending_snapshot,
                "full_send": decision.full_send,
            }
            for decision in plan.decisions
        ],
    }


@router.get("/sync/instructions/{system_id}", response_model=SyncInstructionsResponse)
async def get_sync_instructions(
    system_id: UUID,
    sync_group_id: Optional[UUID] = Query(None, description="Filter by sync group"),
    db: Session = Depends(get_db),
):
    """Get the sync instructions a system is responsible for executing.

    Commands send from the source's pool, so a system receives the pairs where
    it is the source. For a directional group that means the hub receives one
    instruction per lagging target, rather than the single consolidated entry
    the previous implementation produced.

    ``declined`` lists every pair evaluated and not actioned, so an empty
    ``datasets`` explains itself.
    """
    planner = SyncPlanner(db)
    decisions = planner.plan_for_system(system_id=system_id, sync_group_id=sync_group_id)

    instructions: List[DatasetSyncInstruction] = []
    declined: List[DeclinedPair] = [_as_declined(d) for d in decisions if not d.is_sync]

    for decision in decisions:
        if not decision.is_sync:
            continue
        instruction = _as_instruction(decision)
        if instruction is None:
            declined.append(_as_declined(decision))
            continue
        instructions.append(instruction)

    logger.info(
        "System %s: %d instruction(s), %d declined",
        system_id,
        len(instructions),
        len(declined),
    )

    return SyncInstructionsResponse(
        system_id=str(system_id),
        timestamp=datetime.now(timezone.utc).isoformat(),
        datasets=instructions,
        dataset_count=len(instructions),
        declined=declined,
    )


@router.post("/sync/states", response_model=SyncStateResponse, status_code=status.HTTP_201_CREATED)
async def create_or_update_sync_state(
    sync_group_id: UUID,
    dataset: str,
    system_id: UUID,
    status: SyncStatus,
    error_message: Optional[str] = None,
    db: Session = Depends(get_db),
):
    """Create or update a sync state for a dataset."""
    sync_state = SyncStateService(db).update_sync_state(
        sync_group_id=sync_group_id,
        dataset=dataset,
        system_id=system_id,
        status=status,
        error_message=error_message,
    )
    return SyncStateResponse.model_validate(sync_state)


@router.get("/sync/groups/{group_id}/status", response_model=SyncStatusSummary)
async def get_sync_status_summary(group_id: UUID, db: Session = Depends(get_db)):
    """Get sync status summary for a sync group."""
    return SyncStatusSummary(**SyncStateService(db).get_status_summary(group_id))


@router.get("/sync/groups/{group_id}/analysis")
async def analyze_sync_group(group_id: UUID, db: Session = Depends(get_db)) -> Dict[str, Any]:
    """Analyse a sync group: its systems, datasets, and planning outcomes."""
    planner = SyncPlanner(db)
    plan = planner.plan_group(group_id)

    by_dataset: Dict[str, List[SyncDecision]] = {}
    for decision in plan.decisions:
        by_dataset.setdefault(decision.dataset, []).append(decision)

    datasets = []
    for dataset, decisions in sorted(by_dataset.items()):
        datasets.append(
            {
                "dataset_name": dataset,
                "sync_status": "out_of_sync"
                if any(d.is_sync for d in decisions)
                else "in_sync",
                "targets": [
                    {
                        "target_system_id": str(d.target.id),
                        "hostname": d.target.hostname,
                        "pool": d.target_pool,
                        "action": d.action.value,
                        "reason": d.reason,
                        "target_latest": d.target_latest,
                        "hours_behind": d.hours_behind,
                    }
                    for d in decisions
                ],
            }
        )

    return {
        "sync_group_id": str(group_id),
        "skipped_reason": plan.skipped_reason,
        "datasets": datasets,
        "total_datasets": len(datasets),
        "total_pairs": len(plan.decisions),
        "total_requiring_sync": len(plan.instructions),
    }


@router.post(
    "/sync/results",
    response_model=SyncResultResponse,
    status_code=status.HTTP_201_CREATED,
)
async def report_sync_result(result: SyncResultCreate, db: Session = Depends(get_db)):
    """Report how an executed sync instruction went.

    Records an append-only run and projects the outcome into sync_states, so
    the dashboard and status summary reflect what actually happened rather than
    what was merely planned.
    """
    run = SyncOutcomeService(db).record(
        SyncOutcome(
            sync_group_id=result.sync_group_id,
            dataset=result.dataset,
            source_system_id=result.source_system_id,
            target_system_id=result.target_system_id,
            status=RunStatus(result.status),
            starting_snapshot=result.starting_snapshot,
            ending_snapshot=result.ending_snapshot,
            started_at=result.started_at,
            finished_at=result.finished_at,
            duration_seconds=result.duration_seconds,
            bytes_transferred=result.bytes_transferred,
            error_message=result.error_message,
            reported_by_system_id=result.source_system_id,
        )
    )
    return SyncResultResponse.model_validate(run)


@router.get("/sync/groups/{group_id}/runs")
async def get_sync_runs(
    group_id: UUID,
    limit: int = Query(50, ge=1, le=500, description="Maximum runs to return"),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """Recent execution history for a sync group, newest first."""
    runs = SyncOutcomeService(db).recent_runs(group_id, limit=limit)
    return {"sync_group_id": str(group_id), "run_count": len(runs), "runs": runs}
