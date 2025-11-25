"""Authentication middleware for API key validation."""

from typing import Optional
from uuid import UUID

from fastapi import Depends, HTTPException, Security, status
from fastapi.security import APIKeyHeader
from sqlalchemy.orm import Session

from zfs_sync.database import get_db
from zfs_sync.services.auth import AuthService

# API Key header
api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


async def get_current_system(
    api_key: Optional[str] = Security(api_key_header),
    db: Session = Depends(get_db),
) -> UUID:
    """
    Dependency to get the current system from API key.

    Raises 401 if API key is missing or invalid.
    """
    if not api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="API key required",
            headers={"WWW-Authenticate": "ApiKey"},
        )

    auth_service = AuthService(db)
    system_id = auth_service.validate_api_key(api_key)

    if not system_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API key",
            headers={"WWW-Authenticate": "ApiKey"},
        )

    return system_id


async def get_optional_system(
    api_key: Optional[str] = Security(api_key_header),
    db: Session = Depends(get_db),
) -> Optional[UUID]:
    """
    Dependency to optionally get the current system from API key.

    Returns None if API key is missing or invalid (doesn't raise exception).
    """
    if not api_key:
        return None

    auth_service = AuthService(db)
    return auth_service.validate_api_key(api_key)
