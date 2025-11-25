"""Conflict resolution API schemas."""

from typing import Dict, List, Optional

from pydantic import BaseModel, Field

from zfs_sync.services.conflict_resolution import (
    ConflictResolutionStrategy,
)


class ConflictResponse(BaseModel):
    """Schema for conflict response."""

    type: str = Field(..., description="Type of conflict")
    snapshot_name: str = Field(..., description="Name of the conflicting snapshot")
    pool: str = Field(..., description="ZFS pool name")
    dataset: str = Field(..., description="ZFS dataset name")
    sync_group_id: str = Field(..., description="Sync group ID")
    systems: Dict[str, Dict] = Field(..., description="Systems involved in conflict")
    severity: str = Field(..., description="Conflict severity (low, medium, high)")
    detected_at: str = Field(..., description="When conflict was detected")


class ConflictResolutionRequest(BaseModel):
    """Schema for conflict resolution request."""

    strategy: ConflictResolutionStrategy = Field(
        ..., description="Resolution strategy to use"
    )
    resolution_data: Optional[Dict] = Field(
        None, description="Additional data for resolution (e.g., chosen system_id)"
    )


class ConflictResolutionResponse(BaseModel):
    """Schema for conflict resolution response."""

    status: str = Field(..., description="Resolution status")
    strategy: Optional[str] = Field(None, description="Strategy used")
    conflict: Optional[Dict] = Field(None, description="The conflict being resolved")
    actions: Optional[List[Dict]] = Field(None, description="Actions to take")
    message: Optional[str] = Field(None, description="Resolution message")
    resolution_timestamp: Optional[str] = Field(None, description="When resolved")


class ConflictListResponse(BaseModel):
    """Schema for conflict list response."""

    conflicts: List[ConflictResponse] = Field(..., description="List of conflicts")
    count: int = Field(..., description="Number of conflicts")
    sync_group_id: str = Field(..., description="Sync group ID")

