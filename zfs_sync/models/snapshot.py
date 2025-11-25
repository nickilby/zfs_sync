"""Snapshot model representing a ZFS snapshot."""

from datetime import datetime
from typing import Optional
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


class Snapshot(BaseModel):
    """Represents a ZFS snapshot with metadata."""

    id: UUID = Field(default_factory=uuid4, description="Unique identifier for the snapshot")
    name: str = Field(..., description="Name of the snapshot")
    pool: str = Field(..., description="ZFS pool name")
    dataset: str = Field(..., description="ZFS dataset name")
    timestamp: datetime = Field(..., description="When the snapshot was created")
    size: Optional[int] = Field(default=None, description="Size of the snapshot in bytes")
    system_id: UUID = Field(..., description="ID of the system that owns this snapshot")
    referenced: Optional[int] = Field(
        default=None, description="Referenced size in bytes (actual data size)"
    )
    used: Optional[int] = Field(
        default=None, description="Used space in bytes (space unique to this snapshot)"
    )
    metadata: dict = Field(default_factory=dict, description="Additional snapshot metadata")

    class Config:
        """Pydantic configuration."""

        json_schema_extra = {
            "example": {
                "id": "123e4567-e89b-12d3-a456-426614174001",
                "name": "backup-20240115-103000",
                "pool": "tank",
                "dataset": "tank/data",
                "timestamp": "2024-01-15T10:30:00Z",
                "size": 1073741824,
                "system_id": "123e4567-e89b-12d3-a456-426614174000",
                "referenced": 536870912,
                "used": 1048576,
            }
        }

