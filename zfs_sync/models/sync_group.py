"""SyncGroup model for grouping systems that should maintain synchronized snapshots."""

from typing import List
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


class SyncGroup(BaseModel):
    """Groups systems that should maintain synchronized snapshots."""

    id: UUID = Field(default_factory=uuid4, description="Unique identifier for the sync group")
    name: str = Field(..., description="Name of the sync group")
    system_ids: List[UUID] = Field(
        default_factory=list, description="List of system IDs in this sync group"
    )
    enabled: bool = Field(
        default=True, description="Whether synchronization is enabled for this group"
    )
    sync_interval_seconds: int = Field(
        default=3600, description="Interval between sync checks in seconds"
    )
    metadata: dict = Field(default_factory=dict, description="Additional sync group metadata")

    class Config:
        """Pydantic configuration."""

        json_schema_extra = {
            "example": {
                "id": "123e4567-e89b-12d3-a456-426614174002",
                "name": "production-backup-group",
                "system_ids": [
                    "123e4567-e89b-12d3-a456-426614174000",
                    "123e4567-e89b-12d3-a456-426614174001",
                ],
                "enabled": True,
                "sync_interval_seconds": 3600,
            }
        }
