"""Repository for sync run history."""

from typing import List, Optional
from uuid import UUID

from sqlalchemy.orm import Session

from zfs_sync.database.models import SyncRunModel
from zfs_sync.database.repositories.base_repository import BaseRepository


class SyncRunRepository(BaseRepository[SyncRunModel]):
    """Reads and writes the append-only sync run history."""

    def __init__(self, db: Session):
        super().__init__(SyncRunModel, db)

    def get_for_pair(
        self,
        sync_group_id: UUID,
        dataset: str,
        target_system_id: UUID,
        limit: int = 20,
    ) -> List[SyncRunModel]:
        """Return runs for one (group, dataset, target), newest first."""
        return (
            self.db.query(SyncRunModel)
            .filter(
                SyncRunModel.sync_group_id == sync_group_id,
                SyncRunModel.dataset == dataset,
                SyncRunModel.target_system_id == target_system_id,
            )
            .order_by(SyncRunModel.created_at.desc())
            .limit(limit)
            .all()
        )

    def get_for_sync_group(
        self, sync_group_id: UUID, limit: int = 100, status: Optional[str] = None
    ) -> List[SyncRunModel]:
        """Return recent runs for a sync group, newest first."""
        query = self.db.query(SyncRunModel).filter(SyncRunModel.sync_group_id == sync_group_id)
        if status:
            query = query.filter(SyncRunModel.status == status)
        return query.order_by(SyncRunModel.created_at.desc()).limit(limit).all()
