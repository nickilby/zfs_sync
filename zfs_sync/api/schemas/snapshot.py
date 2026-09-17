"""Snapshot API schemas."""

from datetime import datetime
from typing import List, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


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

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


class SnapshotDeleteResponse(BaseModel):
    """Schema for bulk snapshot deletion response."""

    system_id: str = Field(..., description="System ID")
    hostname: str = Field(..., description="System hostname")
    deleted_count: int = Field(..., description="Number of snapshots deleted")
    message: str = Field(..., description="Status message")


class SnapshotIngestFailure(BaseModel):
    """One row the batch could not store, and why."""

    name: str
    pool: str
    dataset: str
    error: str


class SnapshotBatchResponse(BaseModel):
    """Outcome of a batch report.

    The previous response was a bare list of successfully created snapshots,
    so a batch where rows were rejected still returned 201 with a shorter list
    and no way to tell which ones failed -- the detail existed only in the
    server log.
    """

    created: int = Field(..., description="Rows inserted for the first time")
    updated: int = Field(..., description="Rows that already existed and were refreshed")
    deleted: int = Field(..., description="Rows removed because the client no longer reports them")
    failed: List[SnapshotIngestFailure] = Field(
        default_factory=list, description="Rows that could not be stored, with the reason"
    )
    scope: List[str] = Field(
        default_factory=list,
        description=(
            "The pool/dataset pairs this report covered. Reconciliation only "
            "deletes within these, so a partial report cannot remove records "
            "for datasets it said nothing about."
        ),
    )
    snapshots: List[SnapshotResponse] = Field(default_factory=list, description="The stored rows")
