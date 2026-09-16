"""System API schemas."""

import re
from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


# ssh_hostname and ssh_user are interpolated into a command that a client runs
# as root. The generator quotes them, but validating here keeps obviously
# hostile values out of the database in the first place. Permissive enough for
# hostnames, FQDNs, IPv4, IPv6 literals and ssh_config aliases; strict enough to
# exclude whitespace and every shell metacharacter.
_SSH_TARGET_PATTERN = re.compile(r"^[A-Za-z0-9._:%-]{1,255}$")
_SSH_USER_PATTERN = re.compile(r"^[A-Za-z0-9._-]{1,64}$")


def _validate_ssh_hostname(value: Optional[str]) -> Optional[str]:
    """Reject SSH hostnames that could break out of the generated command."""
    if value is None or value == "":
        return value
    if not _SSH_TARGET_PATTERN.match(value):
        raise ValueError(
            "ssh_hostname may contain only letters, digits and . _ - : % "
            "(hostname, FQDN, IPv4, IPv6 or ssh_config alias)"
        )
    return value


def _validate_ssh_user(value: Optional[str]) -> Optional[str]:
    """Reject SSH usernames that could break out of the generated command."""
    if value is None or value == "":
        return value
    if not _SSH_USER_PATTERN.match(value):
        raise ValueError("ssh_user may contain only letters, digits and . _ -")
    return value


class SystemBase(BaseModel):
    """Base system schema."""

    hostname: str = Field(..., description="Hostname of the system")
    platform: str = Field(..., description="Operating system platform")
    connectivity_status: str = Field(default="unknown", description="Connectivity status")
    ssh_hostname: Optional[str] = Field(
        None, description="SSH hostname/IP (can differ from API hostname)"
    )
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

    @field_validator("ssh_hostname")
    @classmethod
    def check_ssh_hostname(cls, v):
        """Reject SSH hostnames containing shell metacharacters."""
        return _validate_ssh_hostname(v)

    @field_validator("ssh_user")
    @classmethod
    def check_ssh_user(cls, v):
        """Reject SSH usernames containing shell metacharacters."""
        return _validate_ssh_user(v)


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

    @field_validator("ssh_hostname")
    @classmethod
    def check_ssh_hostname(cls, v):
        """Reject SSH hostnames containing shell metacharacters."""
        return _validate_ssh_hostname(v)

    @field_validator("ssh_user")
    @classmethod
    def check_ssh_user(cls, v):
        """Reject SSH usernames containing shell metacharacters."""
        return _validate_ssh_user(v)


class SystemResponse(SystemBase):
    """Schema for system response.

    Deliberately carries no ``api_key``. With ``from_attributes=True`` Pydantic
    populates every declared field straight from the ORM row, so declaring the
    key here -- however it was commented -- meant every read path returned it,
    making ``GET /systems`` an unauthenticated dump of the fleet's credentials.
    The key is handed out exactly once, by :class:`SystemCreatedResponse`.
    """

    id: UUID
    last_seen: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


class SystemCreatedResponse(SystemResponse):
    """Registration response -- the only place an API key is returned."""

    api_key: str = Field(..., description="API key. Shown once, at registration.")
