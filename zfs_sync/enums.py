"""Shared enumerations.

``SyncStatus`` previously lived in ``zfs_sync/models/sync_state.py``, alongside
a Pydantic ``SyncState`` that nothing imported. Every entity in this project was
modelled three times -- once there, once in ``database/models.py``, and once in
``api/schemas/`` -- and only the enum from that first layer was ever used.
"""

from enum import Enum


class SyncStatus(str, Enum):
    """Synchronisation status recorded for a (sync group, dataset, system)."""

    IN_SYNC = "in_sync"
    OUT_OF_SYNC = "out_of_sync"
    SYNCING = "syncing"
    CONFLICT = "conflict"
    ERROR = "error"


__all__ = ["SyncStatus"]
