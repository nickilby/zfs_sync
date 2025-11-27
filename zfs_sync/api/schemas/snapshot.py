"""Snapshot API schemas."""

from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, Field, field_validator


class SnapshotBase(BaseModel):
    """Base snapshot schema."""

    name: str = Field(..., description="Name of the snapshot")
    pool: str = Field(..., description="ZFS pool name")
    dataset: str = Field(..., description="ZFS dataset name")
    timestamp: datetime = Field(..., description="When the snapshot was created")
    size: Optional[int] = Field(None, description="Size of the snapshot in bytes")
    referenced: Optional[int] = Field(None, description="Referenced size in bytes")
    used: Optional[int] = Field(None, description="Used space in bytes")
    metadata: Optional[dict] = Field(
        default_factory=dict, alias="extra_metadata", description="Additional metadata"
    )

    @field_validator("metadata", mode="before")
    @classmethod
    def validate_metadata(cls, v):
        """Convert None to empty dict for metadata."""
        if v is None:
            return {}
        return v if isinstance(v, dict) else {}


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
        populate_by_name = True


class SnapshotDeleteResponse(BaseModel):
    """Schema for bulk snapshot deletion response."""

    system_id: str = Field(..., description="System ID")
    hostname: str = Field(..., description="System hostname")
    deleted_count: int = Field(..., description="Number of snapshots deleted")
    message: str = Field(..., description="Status message")
