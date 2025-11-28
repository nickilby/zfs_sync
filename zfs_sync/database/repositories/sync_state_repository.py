"""Repository for SyncState operations."""

from typing import List, Optional
from uuid import UUID

from sqlalchemy.orm import Session

from zfs_sync.database.models import SyncStateModel
from zfs_sync.database.repositories.base_repository import BaseRepository


class SyncStateRepository(BaseRepository[SyncStateModel]):
    """Repository for SyncState database operations."""

    def __init__(self, db: Session):
        """Initialize sync state repository."""
        super().__init__(SyncStateModel, db)

    def get_by_sync_group(self, sync_group_id: UUID) -> List[SyncStateModel]:
        """Get all sync states for a sync group."""
        return (
            self.db.query(SyncStateModel)
            .filter(SyncStateModel.sync_group_id == sync_group_id)
            .all()
        )

    def get_by_dataset(
        self, sync_group_id: UUID, dataset: str, system_id: UUID
    ) -> Optional[SyncStateModel]:
        """Get sync state for a specific dataset, sync group, and system."""
        return (
            self.db.query(SyncStateModel)
            .filter(
                SyncStateModel.sync_group_id == sync_group_id,
                SyncStateModel.dataset == dataset,
                SyncStateModel.system_id == system_id,
            )
            .first()
        )

    def get_by_system(self, system_id: UUID) -> List[SyncStateModel]:
        """Get all sync states for a system."""
        return self.db.query(SyncStateModel).filter(SyncStateModel.system_id == system_id).all()

    def get_by_status(self, status: str) -> List[SyncStateModel]:
        """Get all sync states with a specific status."""
        return self.db.query(SyncStateModel).filter(SyncStateModel.status == status).all()
