"""System API schemas."""

from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, Field, field_validator


class SystemBase(BaseModel):
    """Base system schema."""

    hostname: str = Field(..., description="Hostname of the system")
    platform: str = Field(..., description="Operating system platform")
    connectivity_status: str = Field(default="unknown", description="Connectivity status")
    ssh_hostname: Optional[str] = Field(None, description="SSH hostname/IP (can differ from API hostname)")
    ssh_user: Optional[str] = Field(None, description="SSH username for key-based authentication")
    ssh_port: int = Field(default=22, description="SSH port")
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


class SystemCreate(SystemBase):
    """Schema for creating a system."""

    pass


class SystemUpdate(BaseModel):
    """Schema for updating a system."""

    hostname: Optional[str] = None
    platform: Optional[str] = None
    connectivity_status: Optional[str] = None
    ssh_hostname: Optional[str] = None
    ssh_user: Optional[str] = None
    ssh_port: Optional[int] = None
    last_seen: Optional[datetime] = None
    metadata: Optional[dict] = None


class SystemResponse(SystemBase):
    """Schema for system response."""

    id: UUID
    last_seen: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime
    api_key: Optional[str] = Field(None, description="API key (only returned on creation)")

    class Config:
        """Pydantic configuration."""

        from_attributes = True
        populate_by_name = True
