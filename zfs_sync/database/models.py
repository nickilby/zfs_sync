"""SQLAlchemy database models."""


from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, JSON, String, Text
from sqlalchemy.orm import relationship

from zfs_sync.database.base import BaseModel, GUID


class SystemModel(BaseModel):
    """Database model for ZFS systems."""

    __tablename__ = "systems"

    hostname = Column(String(255), nullable=False, unique=True, index=True)
    platform = Column(String(50), nullable=False)
    connectivity_status = Column(String(20), default="unknown", nullable=False)
    last_seen = Column(DateTime(timezone=True), nullable=True)
    api_key = Column(String(255), nullable=True, unique=True, index=True)
    extra_metadata = Column("metadata", JSON, default=dict)

    # Relationships
    snapshots = relationship("SnapshotModel", back_populates="system", cascade="all, delete-orphan")
    sync_states = relationship("SyncStateModel", back_populates="system", cascade="all, delete-orphan")


class SnapshotModel(BaseModel):
    """Database model for ZFS snapshots."""

    __tablename__ = "snapshots"

    name = Column(String(255), nullable=False, index=True)
    pool = Column(String(100), nullable=False, index=True)
    dataset = Column(String(255), nullable=False, index=True)
    timestamp = Column(DateTime(timezone=True), nullable=False, index=True)
    size = Column(Integer, nullable=True)
    system_id = Column(GUID(), ForeignKey("systems.id"), nullable=False, index=True)
    referenced = Column(Integer, nullable=True)
    used = Column(Integer, nullable=True)
    extra_metadata = Column("metadata", JSON, default=dict)

    # Relationships
    system = relationship("SystemModel", back_populates="snapshots")
    sync_states = relationship("SyncStateModel", back_populates="snapshot", cascade="all, delete-orphan")


class SyncGroupModel(BaseModel):
    """Database model for sync groups."""

    __tablename__ = "sync_groups"

    name = Column(String(255), nullable=False, unique=True, index=True)
    enabled = Column(Boolean, default=True, nullable=False)
    sync_interval_seconds = Column(Integer, default=3600, nullable=False)
    extra_metadata = Column("metadata", JSON, default=dict)

    # Many-to-many relationship with systems
    system_associations = relationship("SyncGroupSystemModel", back_populates="sync_group", cascade="all, delete-orphan")


class SyncGroupSystemModel(BaseModel):
    """Association table for sync groups and systems."""

    __tablename__ = "sync_group_systems"

    sync_group_id = Column(GUID(), ForeignKey("sync_groups.id"), nullable=False, index=True)
    system_id = Column(GUID(), ForeignKey("systems.id"), nullable=False, index=True)

    # Relationships
    sync_group = relationship("SyncGroupModel", back_populates="system_associations")
    system = relationship("SystemModel")


class SyncStateModel(BaseModel):
    """Database model for synchronization states."""

    __tablename__ = "sync_states"

    sync_group_id = Column(GUID(), ForeignKey("sync_groups.id"), nullable=False, index=True)
    snapshot_id = Column(GUID(), ForeignKey("snapshots.id"), nullable=False, index=True)
    system_id = Column(GUID(), ForeignKey("systems.id"), nullable=False, index=True)
    status = Column(String(20), nullable=False, default="out_of_sync", index=True)
    last_sync = Column(DateTime(timezone=True), nullable=True)
    last_check = Column(DateTime(timezone=True), nullable=True)
    error_message = Column(Text, nullable=True)
    extra_metadata = Column("metadata", JSON, default=dict)

    # Relationships
    sync_group = relationship("SyncGroupModel")
    snapshot = relationship("SnapshotModel", back_populates="sync_states")
    system = relationship("SystemModel", back_populates="sync_states")

