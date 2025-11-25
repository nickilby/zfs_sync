"""SyncState model for tracking synchronization state between systems."""

from datetime import datetime
from enum import Enum
from typing import List, Optional
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


class SyncStatus(str, Enum):
    """Status of synchronization."""

    IN_SYNC = "in_sync"
    OUT_OF_SYNC = "out_of_sync"
    SYNCING = "syncing"
    CONFLICT = "conflict"
    ERROR = "error"


class SyncState(BaseModel):
    """Tracks the synchronization state between systems."""

    id: UUID = Field(default_factory=uuid4, description="Unique identifier for the sync state")
    sync_group_id: UUID = Field(..., description="ID of the sync group this state belongs to")
    snapshot_id: UUID = Field(..., description="ID of the snapshot being tracked")
    system_ids: List[UUID] = Field(
        ..., description="List of system IDs that should have this snapshot"
    )
    status: SyncStatus = Field(default=SyncStatus.OUT_OF_SYNC, description="Current sync status")
    last_sync: Optional[datetime] = Field(
        default=None, description="Timestamp of last successful synchronization"
    )
    last_check: Optional[datetime] = Field(default=None, description="Timestamp of last sync check")
    error_message: Optional[str] = Field(default=None, description="Error message if sync failed")
    metadata: dict = Field(default_factory=dict, description="Additional sync state metadata")

    class Config:
        """Pydantic configuration."""

        json_schema_extra = {
            "example": {
                "id": "123e4567-e89b-12d3-a456-426614174003",
                "sync_group_id": "123e4567-e89b-12d3-a456-426614174002",
                "snapshot_id": "123e4567-e89b-12d3-a456-426614174001",
                "system_ids": [
                    "123e4567-e89b-12d3-a456-426614174000",
                    "123e4567-e89b-12d3-a456-426614174001",
                ],
                "status": "in_sync",
                "last_sync": "2024-01-15T10:30:00Z",
                "last_check": "2024-01-15T11:30:00Z",
            }
        }
