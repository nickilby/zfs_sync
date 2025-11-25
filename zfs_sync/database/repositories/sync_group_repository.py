"""Repository for SyncGroup operations."""

from typing import List, Optional

from sqlalchemy.orm import Session

from zfs_sync.database.models import SyncGroupModel
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
