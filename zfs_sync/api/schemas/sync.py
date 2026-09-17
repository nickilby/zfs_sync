"""Sync state API schemas."""

from datetime import datetime
from typing import List, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from zfs_sync.enums import SyncStatus


class SyncStateResponse(BaseModel):
    """Schema for sync state response."""

    id: UUID
    sync_group_id: UUID
    dataset: str
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

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


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
    # The client rebuilds the command as an argument vector rather than
    # evaluating the rendered string, so it needs the whole target identity.
    target_ssh_user: Optional[str] = Field(None, description="SSH username for target system")
    target_ssh_port: int = Field(default=22, description="SSH port for target system")
    # Required to report the outcome back against the right pair.
    source_system_id: str = Field(..., description="System that runs the send")
    target_system_id: str = Field(..., description="System that receives")
    sync_group_id: str = Field(..., description="Sync group ID")
    requires_rollback: bool = Field(
        default=False,
        description=(
            "The target holds snapshots the source does not, taken after the "
            "starting snapshot. The command therefore includes 'zfs receive -F', "
            "which discards them."
        ),
    )
    commands: List[str] = Field(
        default_factory=list,
        description=(
            "Ready-to-execute sync commands for this dataset "
            "(e.g. 'zfs send -c -I ... | ssh ... zfs receive ...')."
        ),
    )


class DeclinedPair(BaseModel):
    """A (dataset, target) pair the planner considered and did not action.

    Returned alongside the instructions so that an empty ``datasets`` list is
    self-explaining. Previously the only record of these decisions was a log
    line, which meant a healthy fleet and a completely suppressed one produced
    an identical response.
    """

    dataset: str = Field(..., description="Dataset that was evaluated")
    target_system_id: str = Field(..., description="Target system that was evaluated")
    target_hostname: Optional[str] = Field(None, description="Target hostname, for readability")
    reason: Optional[str] = Field(
        None,
        description=(
            "Machine-readable reason, e.g. in_sync_within_window, "
            "no_eligible_ending_snapshot, target_diverged, missing_ssh_identity"
        ),
    )
    source_latest: Optional[str] = Field(None, description="Newest snapshot on the source")
    target_latest: Optional[str] = Field(None, description="Newest snapshot on the target")
    hours_behind: Optional[float] = Field(
        None, description="How far the target trails the source, in hours"
    )


class SyncInstructionsResponse(BaseModel):
    """Schema for sync instructions response (dataset-grouped format)."""

    system_id: str = Field(..., description="System ID requesting instructions")
    timestamp: str = Field(..., description="Timestamp of instruction generation")
    datasets: List[DatasetSyncInstruction] = Field(
        ..., description="List of dataset sync instructions"
    )
    dataset_count: int = Field(..., description="Number of datasets requiring sync")
    declined: List[DeclinedPair] = Field(
        default_factory=list,
        description="Every pair that was evaluated and not actioned, with its reason",
    )


class SyncResultCreate(BaseModel):
    """A client's report of how an execution went.

    Posted after running (or failing to run) an instruction. This is the only
    way the witness learns whether the commands it issues actually work.
    """

    sync_group_id: UUID = Field(..., description="Sync group the instruction came from")
    dataset: str = Field(..., description="Dataset that was synced")
    source_system_id: UUID = Field(..., description="System that ran the send")
    target_system_id: UUID = Field(..., description="System that received")
    status: str = Field(..., description="success, failed, or started")
    starting_snapshot: Optional[str] = Field(None, description="Incremental base that was used")
    ending_snapshot: Optional[str] = Field(None, description="Snapshot sent up to")
    started_at: Optional[datetime] = Field(None, description="When execution began")
    finished_at: Optional[datetime] = Field(None, description="When execution ended")
    duration_seconds: Optional[int] = Field(None, ge=0, description="Wall-clock duration")
    bytes_transferred: Optional[int] = Field(None, ge=0, description="Bytes sent")
    error_message: Optional[str] = Field(None, description="Failure detail, if it failed")

    @field_validator("status")
    @classmethod
    def validate_status(cls, v: str) -> str:
        """Reject a status the projection would not know what to do with."""
        allowed = {"success", "failed", "started"}
        if v not in allowed:
            raise ValueError(f"status must be one of {sorted(allowed)}, got {v!r}")
        return v


class SyncResultResponse(BaseModel):
    """Acknowledgement of a recorded outcome."""

    id: UUID
    sync_group_id: UUID
    dataset: str
    source_system_id: UUID
    target_system_id: UUID
    status: str
    starting_snapshot: Optional[str] = None
    ending_snapshot: Optional[str] = None
    bytes_transferred: Optional[int] = None
    error_message: Optional[str] = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
