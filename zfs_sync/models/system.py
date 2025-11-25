"""System model representing a ZFS system."""

from datetime import datetime
from typing import Optional
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


class System(BaseModel):
    """Represents a ZFS system with metadata."""

    id: UUID = Field(default_factory=uuid4, description="Unique identifier for the system")
    hostname: str = Field(..., description="Hostname of the system")
    platform: str = Field(..., description="Operating system platform (e.g., 'linux', 'freebsd')")
    connectivity_status: str = Field(
        default="unknown", description="Current connectivity status (online, offline, unknown)"
    )
    ssh_hostname: Optional[str] = Field(None, description="SSH hostname/IP (can differ from API hostname)")
    ssh_user: Optional[str] = Field(None, description="SSH username for key-based authentication")
    ssh_port: int = Field(default=22, description="SSH port")
    last_seen: Optional[datetime] = Field(
        default=None, description="Timestamp of last successful communication"
    )
    api_key: Optional[str] = Field(default=None, description="API key for authentication")
    metadata: dict = Field(default_factory=dict, description="Additional system metadata")

    class Config:
        """Pydantic configuration."""

        json_schema_extra = {
            "example": {
                "id": "123e4567-e89b-12d3-a456-426614174000",
                "hostname": "zfs-server-01",
                "platform": "linux",
                "connectivity_status": "online",
                "last_seen": "2024-01-15T10:30:00Z",
                "metadata": {"pool_count": 3, "zfs_version": "2.1.0"},
            }
        }
