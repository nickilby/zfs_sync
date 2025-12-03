"""SQLAlchemy database models."""

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, JSON, String, Text
from sqlalchemy.orm import relationship

from zfs_sync.database.base import BaseModel, GUID


class SystemModel(BaseModel):
    """Database model for ZFS systems."""

    __tablename__ = "systems"

    hostname = Column(String(255), nullable=False, unique=True, index=True)  # type: ignore[assignment]
    platform = Column(String(50), nullable=False)  # type: ignore[assignment]
    connectivity_status = Column(String(20), default="unknown", nullable=False)  # type: ignore[assignment]
    last_seen = Column(DateTime(timezone=True), nullable=True)  # type: ignore[assignment]
    api_key = Column(String(255), nullable=True, unique=True, index=True)  # type: ignore[assignment]
    ssh_hostname = Column(String(255), nullable=True, index=True)  # type: ignore[assignment]
    ssh_user = Column(String(100), nullable=True)  # type: ignore[assignment]
    ssh_port = Column(Integer, default=22, nullable=False)  # type: ignore[assignment]
    extra_metadata = Column("metadata", JSON, default=dict)  # type: ignore[assignment]

    # Relationships
    snapshots = relationship("SnapshotModel", back_populates="system", cascade="all, delete-orphan")
    sync_states = relationship(
        "SyncStateModel", back_populates="system", cascade="all, delete-orphan"
    )


class SnapshotModel(BaseModel):
    """Database model for ZFS snapshots."""

    __tablename__ = "snapshots"

    name = Column(String(255), nullable=False, index=True)  # type: ignore[assignment]
    pool = Column(String(100), nullable=False, index=True)  # type: ignore[assignment]
    dataset = Column(String(255), nullable=False, index=True)  # type: ignore[assignment]
    timestamp = Column(DateTime(timezone=True), nullable=False, index=True)  # type: ignore[assignment]
    size = Column(Integer, nullable=True)  # type: ignore[assignment]
    system_id = Column(GUID(), ForeignKey("systems.id"), nullable=False, index=True)  # type: ignore[assignment]
    referenced = Column(Integer, nullable=True)  # type: ignore[assignment]
    used = Column(Integer, nullable=True)  # type: ignore[assignment]
    extra_metadata = Column("metadata", JSON, default=dict)  # type: ignore[assignment]

    # Relationships
    system = relationship("SystemModel", back_populates="snapshots")


class SyncGroupModel(BaseModel):
    """Database model for sync groups."""

    __tablename__ = "sync_groups"

    name = Column(String(255), nullable=False, unique=True, index=True)  # type: ignore[assignment]
    description = Column(Text, nullable=True)  # type: ignore[assignment]
    enabled = Column(Boolean, default=True, nullable=False)  # type: ignore[assignment]
    sync_interval_seconds = Column(Integer, default=3600, nullable=False)  # type: ignore[assignment]
    directional = Column(Boolean, default=False, nullable=False)  # type: ignore[assignment]
    hub_system_id = Column(GUID(), ForeignKey("systems.id"), nullable=True, index=True)  # type: ignore[assignment]
    extra_metadata = Column("metadata", JSON, default=dict)  # type: ignore[assignment]

    # Many-to-many relationship with systems
    system_associations = relationship(
        "SyncGroupSystemModel", back_populates="sync_group", cascade="all, delete-orphan"
    )

    # Relationship to hub system
    hub_system = relationship("SystemModel", foreign_keys=[hub_system_id])


class SyncGroupSystemModel(BaseModel):
    """Association table for sync groups and systems."""

    __tablename__ = "sync_group_systems"

    sync_group_id = Column(GUID(), ForeignKey("sync_groups.id"), nullable=False, index=True)  # type: ignore[assignment]
    system_id = Column(GUID(), ForeignKey("systems.id"), nullable=False, index=True)  # type: ignore[assignment]

    # Relationships
    sync_group = relationship("SyncGroupModel", back_populates="system_associations")
    system = relationship("SystemModel")


class SyncStateModel(BaseModel):
    """Database model for synchronization states."""

    __tablename__ = "sync_states"

    sync_group_id = Column(GUID(), ForeignKey("sync_groups.id"), nullable=False, index=True)  # type: ignore[assignment]
    dataset = Column(String(255), nullable=False, index=True)  # type: ignore[assignment]
    system_id = Column(GUID(), ForeignKey("systems.id"), nullable=False, index=True)  # type: ignore[assignment]
    status = Column(String(20), nullable=False, default="out_of_sync", index=True)  # type: ignore[assignment]
    last_sync = Column(DateTime(timezone=True), nullable=True)  # type: ignore[assignment]
    last_check = Column(DateTime(timezone=True), nullable=True)  # type: ignore[assignment]
    error_message = Column(Text, nullable=True)  # type: ignore[assignment]
    extra_metadata = Column("metadata", JSON, default=dict)  # type: ignore[assignment]

    # Relationships
    sync_group = relationship("SyncGroupModel")
    system = relationship("SystemModel", back_populates="sync_states")
