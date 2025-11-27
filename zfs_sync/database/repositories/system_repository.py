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

    def get_by_ssh_hostname(self, ssh_hostname: str) -> Optional[SystemModel]:
        """Get a system by SSH hostname."""
        return self.db.query(SystemModel).filter(SystemModel.ssh_hostname == ssh_hostname).first()

    def has_complete_ssh_config(self, system_id: str) -> bool:
        """
        Check if a system has complete SSH configuration.

        Args:
            system_id: UUID of the system to check

        Returns:
            True if system has ssh_hostname configured, False otherwise
        """
        system = self.get(system_id)
        if not system:
            return False
        return system.ssh_hostname is not None and system.ssh_hostname != ""
