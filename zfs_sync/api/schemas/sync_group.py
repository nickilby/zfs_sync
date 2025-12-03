"""Sync group API schemas."""

from datetime import datetime
from typing import List, Optional
from uuid import UUID

from pydantic import BaseModel, Field, field_validator, model_validator


class SyncGroupBase(BaseModel):
    """Base sync group schema."""

    name: str = Field(..., description="Name of the sync group")
    enabled: bool = Field(default=True, description="Whether synchronization is enabled")
    sync_interval_seconds: int = Field(
        default=3600, description="Interval between sync checks in seconds"
    )
    directional: bool = Field(
        default=False, description="Whether this is a directional (hub-and-spoke) sync group"
    )
    hub_system_id: Optional[UUID] = Field(
        default=None,
        description="Hub system ID for directional sync (required when directional=True)",
    )
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

    @model_validator(mode="after")
    def validate_directional_sync(self):
        """Validate that hub_system_id is provided when directional=True."""
        if self.directional and self.hub_system_id is None:
            raise ValueError("hub_system_id is required when directional=True")
        return self


class SyncGroupCreate(SyncGroupBase):
    """Schema for creating a sync group."""

    system_ids: List[UUID] = Field(..., description="List of system IDs in this sync group")


class SyncGroupUpdate(BaseModel):
    """Schema for updating a sync group."""

    name: Optional[str] = None
    enabled: Optional[bool] = None
    sync_interval_seconds: Optional[int] = None
    directional: Optional[bool] = None
    hub_system_id: Optional[UUID] = None
    system_ids: Optional[List[UUID]] = None
    metadata: Optional[dict] = None


class SyncGroupResponse(SyncGroupBase):
    """Schema for sync group response."""

    id: UUID
    system_ids: List[UUID] = Field(
        default_factory=list, description="List of system IDs in this sync group"
    )
    created_at: datetime
    updated_at: datetime

    class Config:
        """Pydantic configuration."""

        from_attributes = True
        populate_by_name = True
