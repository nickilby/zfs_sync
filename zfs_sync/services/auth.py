"""Authentication and authorization services."""

import secrets
from typing import Optional
from uuid import UUID

from sqlalchemy.orm import Session

from zfs_sync.config import get_settings
from zfs_sync.database.repositories import SystemRepository
from zfs_sync.logging_config import get_logger

logger = get_logger(__name__)


class AuthService:
    """Service for authentication and API key management."""

    def __init__(self, db: Session):
        """Initialize the auth service."""
        self.db = db
        self.system_repo = SystemRepository(db)
        self.settings = get_settings()

    def generate_api_key(self) -> str:
        """Generate a secure API key."""
        # Generate a URL-safe random token
        api_key = secrets.token_urlsafe(self.settings.api_key_length)
        return api_key

    def create_api_key_for_system(self, system_id: UUID) -> str:
        """Generate and assign an API key to a system."""
        system = self.system_repo.get(system_id)
        if not system:
            raise ValueError(
                f"System '{system_id}' not found. "
                f"Cannot create API key for non-existent system."
            )

        api_key = self.generate_api_key()
        self.system_repo.update(system_id, api_key=api_key)
        logger.info(f"Generated API key for system {system_id}")
        return api_key

    def validate_api_key(self, api_key: str) -> Optional[UUID]:
        """
        Validate an API key and return the system ID if valid.

        Returns:
            System ID if valid, None otherwise
        """
        if not api_key:
            return None

        system = self.system_repo.get_by_api_key(api_key)
        if system:
            # Update last_seen timestamp
            from datetime import datetime, timezone

            self.system_repo.update(system.id, last_seen=datetime.now(timezone.utc))
            return system.id
        return None

    def revoke_api_key(self, system_id: UUID) -> None:
        """Revoke (remove) an API key from a system."""
        system = self.system_repo.get(system_id)
        if not system:
            raise ValueError(
                f"System '{system_id}' not found. "
                f"Cannot create API key for non-existent system."
            )

        self.system_repo.update(system_id, api_key=None)
        logger.info(f"Revoked API key for system {system_id}")

    def rotate_api_key(self, system_id: UUID) -> str:
        """Rotate (generate new) API key for a system."""
        new_key = self.create_api_key_for_system(system_id)
        logger.info(f"Rotated API key for system {system_id}")
        return new_key

