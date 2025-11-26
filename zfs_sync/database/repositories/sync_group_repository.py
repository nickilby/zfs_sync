"""Repository for SyncGroup operations."""

from typing import List, Optional
from uuid import UUID

from sqlalchemy.orm import Session

from zfs_sync.database.models import SyncGroupModel, SyncGroupSystemModel
from zfs_sync.database.repositories.base_repository import BaseRepository


class SyncGroupRepository(BaseRepository[SyncGroupModel]):
    """Repository for SyncGroup database operations."""

    def __init__(self, db: Session):
        """Initialize sync group repository."""
        super().__init__(SyncGroupModel, db)

    def get_by_name(self, name: str) -> Optional[SyncGroupModel]:
        """Get a sync group by name."""
        return self.db.query(SyncGroupModel).filter(SyncGroupModel.name == name).first()

    def get_enabled(self) -> List[SyncGroupModel]:
        """Get all enabled sync groups."""
        return self.db.query(SyncGroupModel).filter(SyncGroupModel.enabled).all()

    def add_system(self, sync_group_id: UUID, system_id: UUID) -> None:
        """Add a system to a sync group by creating an association."""
        # Check if association already exists
        existing = (
            self.db.query(SyncGroupSystemModel)
            .filter(
                SyncGroupSystemModel.sync_group_id == sync_group_id,
                SyncGroupSystemModel.system_id == system_id,
            )
            .first()
        )
        if existing:
            return  # Already associated

        # Create new association
        association = SyncGroupSystemModel(sync_group_id=sync_group_id, system_id=system_id)
        self.db.add(association)
        self.db.commit()
