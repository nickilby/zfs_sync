"""System API schemas."""

from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, Field


class SystemBase(BaseModel):
    """Base system schema."""

    hostname: str = Field(..., description="Hostname of the system")
    platform: str = Field(..., description="Operating system platform")
    connectivity_status: str = Field(default="unknown", description="Connectivity status")
    metadata: dict = Field(default_factory=dict, description="Additional metadata")


class SystemCreate(SystemBase):
    """Schema for creating a system."""

    pass


class SystemUpdate(BaseModel):
    """Schema for updating a system."""

    hostname: Optional[str] = None
    platform: Optional[str] = None
    connectivity_status: Optional[str] = None
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

