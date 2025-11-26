"""Service for monitoring system health and connectivity."""

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from uuid import UUID

from sqlalchemy.orm import Session

from zfs_sync.config import get_settings
from zfs_sync.database.repositories import SystemRepository
from zfs_sync.logging_config import get_logger

logger = get_logger(__name__)


class SystemHealthService:
    """Service for monitoring system health."""

    def __init__(self, db: Session):
        """Initialize the health service."""
        self.db = db
        self.system_repo = SystemRepository(db)
        self.settings = get_settings()

    def record_heartbeat(self, system_id: UUID, metadata: Optional[Dict] = None) -> Dict[str, Any]:
        """
        Record a heartbeat from a system.

        Updates last_seen timestamp and connectivity status.
        """
        system = self.system_repo.get(system_id)
        if not system:
            raise ValueError(
                f"System '{system_id}' not found. "
                f"Cannot record heartbeat for non-existent system."
            )

        now = datetime.now(timezone.utc)
        self.system_repo.update(
            system_id,
            last_seen=now,
            connectivity_status="online",
            extra_metadata=metadata or {},
        )

        logger.debug(f"Heartbeat recorded for system {system_id}")

        return {
            "system_id": str(system_id),
            "last_seen": now.isoformat(),
            "status": "online",
        }

    def check_system_health(self, system_id: UUID) -> Dict[str, Any]:
        """
        Check the health status of a system.

        Returns health information including connectivity status.
        """
        system = self.system_repo.get(system_id)
        if not system:
            raise ValueError(
                f"System '{system_id}' not found. "
                f"Cannot record heartbeat for non-existent system."
            )

        now = datetime.now(timezone.utc)
        timeout_seconds = self.settings.heartbeat_timeout_seconds

        # Determine if system is online based on last_seen
        is_online = False
        if system.last_seen:
            time_since_last_seen = (now - system.last_seen).total_seconds()
            is_online = time_since_last_seen < timeout_seconds

        # Update connectivity status if needed
        new_status = "online" if is_online else "offline"
        if system.connectivity_status != new_status:
            self.system_repo.update(system_id, connectivity_status=new_status)
            logger.info(f"System {system_id} status changed to {new_status}")

        return {
            "system_id": str(system_id),
            "hostname": system.hostname,
            "status": new_status,
            "last_seen": system.last_seen.isoformat() if system.last_seen else None,
            "seconds_since_last_seen": (
                (now - system.last_seen).total_seconds() if system.last_seen else None
            ),
            "timeout_seconds": timeout_seconds,
            "is_healthy": is_online,
        }

    def get_all_systems_health(self) -> List[Dict[str, Any]]:
        """Get health status for all systems."""
        systems = self.system_repo.get_all()
        health_statuses = []

        for system in systems:
            try:
                health = self.check_system_health(system.id)
                health_statuses.append(health)
            except Exception as e:
                logger.error(f"Error checking health for system {system.id}: {e}")
                health_statuses.append(
                    {
                        "system_id": str(system.id),
                        "hostname": system.hostname,
                        "status": "unknown",
                        "error": str(e),
                    }
                )

        return health_statuses

    def get_offline_systems(self) -> List[Dict[str, Any]]:
        """Get list of systems that are currently offline."""
        all_health = self.get_all_systems_health()
        return [h for h in all_health if h.get("status") == "offline"]

    def get_online_systems(self) -> List[Dict[str, Any]]:
        """Get list of systems that are currently online."""
        all_health = self.get_all_systems_health()
        return [h for h in all_health if h.get("status") == "online"]
