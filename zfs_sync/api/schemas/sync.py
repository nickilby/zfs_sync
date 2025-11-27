"""Sync state API schemas."""

from datetime import datetime
from typing import List, Optional
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

from zfs_sync.models import SyncStatus


class SyncStateResponse(BaseModel):
    """Schema for sync state response."""

    id: UUID
    sync_group_id: UUID
    snapshot_id: UUID
    system_id: UUID
    status: SyncStatus
    last_sync: Optional[datetime] = None
    last_check: Optional[datetime] = None
    error_message: Optional[str] = None
    metadata: Optional[dict] = Field(default_factory=dict, alias="extra_metadata")
    created_at: datetime
    updated_at: datetime

    @field_validator("metadata", mode="before")
    @classmethod
    def validate_metadata(cls, v):
        """Convert None to empty dict for metadata."""
        if v is None:
            return {}
        return v if isinstance(v, dict) else {}

    class Config:
        """Pydantic configuration."""

        from_attributes = True
        populate_by_name = True


class SyncActionResponse(BaseModel):
    """Schema for sync action response."""

    action_type: str = Field(..., description="Type of action (e.g., 'sync_snapshot')")
    sync_group_id: str = Field(..., description="Sync group ID")
    pool: str = Field(..., description="ZFS pool name")
    dataset: str = Field(..., description="ZFS dataset name")
    target_system_id: str = Field(..., description="System that needs the snapshot")
    source_system_id: str = Field(..., description="System that has the snapshot")
    snapshot_name: str = Field(..., description="Name of snapshot to sync")
    snapshot_id: Optional[str] = Field(
        None, description="Snapshot ID from source system (for sync state updates)"
    )
    priority: int = Field(..., description="Priority of this action (higher = more important)")
    estimated_size: Optional[int] = Field(None, description="Estimated size in bytes")
    source_ssh_hostname: Optional[str] = Field(
        None, description="SSH hostname/IP for source system"
    )
    source_ssh_user: Optional[str] = Field(None, description="SSH username for source system")
    source_ssh_port: int = Field(default=22, description="SSH port for source system")
    sync_command: Optional[str] = Field(
        None, description="Ready-to-execute sync command (SSH send piped to local receive)"
    )
    incremental_base: Optional[str] = Field(
        None, description="Base snapshot name for incremental send (if applicable)"
    )
    is_incremental: bool = Field(default=False, description="Whether this is an incremental send")


class SyncStatusSummary(BaseModel):
    """Schema for sync status summary."""

    sync_group_id: str
    total_states: int
    status_breakdown: dict = Field(..., description="Count of each status type")
    in_sync_count: int
    out_of_sync_count: int
    syncing_count: int
    conflict_count: int
    error_count: int
    last_updated: Optional[datetime] = None


class DatasetSyncInstruction(BaseModel):
    """Schema for a dataset sync instruction."""

    pool: str = Field(..., description="Source ZFS pool name")
    dataset: str = Field(..., description="Source ZFS dataset name")
    target_pool: str = Field(..., description="Target ZFS pool name")
    target_dataset: str = Field(..., description="Target ZFS dataset name")
    starting_snapshot: Optional[str] = Field(
        None, description="Starting snapshot name (incremental base, None for full sync)"
    )
    ending_snapshot: str = Field(..., description="Ending snapshot name (latest to sync)")
    source_ssh_hostname: Optional[str] = Field(None, description="SSH hostname for source system")
    target_ssh_hostname: Optional[str] = Field(None, description="SSH hostname for target system")
    sync_group_id: str = Field(..., description="Sync group ID")


class SyncInstructionsResponse(BaseModel):
    """Schema for sync instructions response (dataset-grouped format)."""

    system_id: str = Field(..., description="System ID requesting instructions")
    timestamp: str = Field(..., description="Timestamp of instruction generation")
    datasets: List[DatasetSyncInstruction] = Field(
        ..., description="List of dataset sync instructions"
    )
    dataset_count: int = Field(..., description="Number of datasets requiring sync")
