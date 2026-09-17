"""Recording and summarising sync state.

``sync_states`` is a current-status projection: one row per
``(sync group, dataset, system)`` saying where that pair stands right now.

It is worth being precise about what writes it, because today almost nothing
does. The scheduler calls a method that returns instructions and discards them,
despite a docstring claiming it updates state, so in practice only conflict
resolution ever writes a row. Everything the dashboard and the status summary
display is therefore either a conflict or stale.
"""

from datetime import datetime, timezone
from typing import Any, Dict, Optional
from uuid import UUID

from sqlalchemy.orm import Session

from zfs_sync.database.models import SyncStateModel
from zfs_sync.database.repositories import SyncStateRepository
from zfs_sync.enums import SyncStatus
from zfs_sync.logging_config import get_logger

logger = get_logger(__name__)


class SyncStateService:
    """Reads and writes the sync-state projection."""

    def __init__(self, db: Session):
        self.db = db
        self.sync_state_repo = SyncStateRepository(db)

    def update_sync_state(
        self,
        sync_group_id: UUID,
        dataset: str,
        system_id: UUID,
        status: SyncStatus,
        error_message: Optional[str] = None,
    ) -> SyncStateModel:
        """Create or update the state row for one (group, dataset, system)."""
        existing = self.sync_state_repo.get_by_dataset(
            sync_group_id=sync_group_id, dataset=dataset, system_id=system_id
        )
        now = datetime.now(timezone.utc)

        if existing:
            existing.status = status.value
            existing.last_check = now
            if status == SyncStatus.IN_SYNC:
                existing.last_sync = now
            existing.error_message = error_message or None
            self.db.commit()
            self.db.refresh(existing)
            return existing

        return self.sync_state_repo.create(
            sync_group_id=sync_group_id,
            dataset=dataset,
            system_id=system_id,
            status=status.value,
            last_check=now,
            last_sync=now if status == SyncStatus.IN_SYNC else None,
            error_message=error_message,
        )

    def get_status_summary(self, sync_group_id: UUID) -> Dict[str, Any]:
        """Summarise the recorded states for a sync group."""
        states = self.sync_state_repo.get_by_sync_group(sync_group_id)

        breakdown: Dict[str, int] = {}
        for state in states:
            breakdown[state.status] = breakdown.get(state.status, 0) + 1

        return {
            "sync_group_id": str(sync_group_id),
            "total_states": len(states),
            "status_breakdown": breakdown,
            "in_sync_count": breakdown.get(SyncStatus.IN_SYNC.value, 0),
            "out_of_sync_count": breakdown.get(SyncStatus.OUT_OF_SYNC.value, 0),
            "syncing_count": breakdown.get(SyncStatus.SYNCING.value, 0),
            "conflict_count": breakdown.get(SyncStatus.CONFLICT.value, 0),
            "error_count": breakdown.get(SyncStatus.ERROR.value, 0),
            "last_updated": max(
                (state.last_check for state in states if state.last_check), default=None
            ),
        }


__all__ = ["SyncStateService"]
