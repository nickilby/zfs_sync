"""Snapshot API schemas."""

from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, Field


class SnapshotBase(BaseModel):
    """Base snapshot schema."""

    name: str = Field(..., description="Name of the snapshot")
    pool: str = Field(..., description="ZFS pool name")
    dataset: str = Field(..., description="ZFS dataset name")
    timestamp: datetime = Field(..., description="When the snapshot was created")
    size: Optional[int] = Field(None, description="Size of the snapshot in bytes")
    referenced: Optional[int] = Field(None, description="Referenced size in bytes")
    used: Optional[int] = Field(None, description="Used space in bytes")
    metadata: dict = Field(default_factory=dict, description="Additional metadata")


class SnapshotCreate(SnapshotBase):
    """Schema for creating a snapshot."""

    system_id: UUID = Field(..., description="ID of the system that owns this snapshot")


class SnapshotResponse(SnapshotBase):
    """Schema for snapshot response."""

    id: UUID
    system_id: UUID
    created_at: datetime
    updated_at: datetime

    class Config:
        """Pydantic configuration."""

        from_attributes = True

