"""Repository for System operations."""

from typing import List, Optional

from sqlalchemy.orm import Session

from zfs_sync.database.models import SystemModel
from zfs_sync.database.repositories.base_repository import BaseRepository


class SystemRepository(BaseRepository[SystemModel]):
    """Repository for System database operations."""

    def __init__(self, db: Session):
        """Initialize system repository."""
        super().__init__(SystemModel, db)

    def get_by_hostname(self, hostname: str) -> Optional[SystemModel]:
        """Get a system by hostname."""
        return self.db.query(SystemModel).filter(SystemModel.hostname == hostname).first()

    def get_by_api_key(self, api_key: str) -> Optional[SystemModel]:
        """Get a system by API key."""
        return self.db.query(SystemModel).filter(SystemModel.api_key == api_key).first()

    def get_all_online(self) -> List[SystemModel]:
        """Get all online systems."""
        return self.db.query(SystemModel).filter(SystemModel.connectivity_status == "online").all()
