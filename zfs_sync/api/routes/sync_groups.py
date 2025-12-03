"""Sync group management endpoints."""

from typing import List
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from zfs_sync.api.schemas.sync_group import SyncGroupCreate, SyncGroupResponse, SyncGroupUpdate
from zfs_sync.database import get_db
from zfs_sync.database.repositories import SyncGroupRepository
from zfs_sync.logging_config import get_logger

logger = get_logger(__name__)
router = APIRouter()


@router.post("/sync-groups", response_model=SyncGroupResponse, status_code=status.HTTP_201_CREATED)
async def create_sync_group(group: SyncGroupCreate, db: Session = Depends(get_db)):
    """Create a new sync group."""
    repo = SyncGroupRepository(db)
    existing = repo.get_by_name(group.name)
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Sync group with name {group.name} already exists",
        )

    # Validate hub_system_id if directional
    if group.directional and group.hub_system_id:
        if group.hub_system_id not in group.system_ids:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="hub_system_id must be one of the systems in the sync group",
            )

    # Create the sync group
    db_group = repo.create(**group.model_dump(exclude={"system_ids"}, by_alias=True))

    # Add system associations
    from zfs_sync.database.models import SyncGroupSystemModel

    for system_id in group.system_ids:
        association = SyncGroupSystemModel(sync_group_id=db_group.id, system_id=system_id)
        db.add(association)

    db.commit()
    db.refresh(db_group)

    logger.info(f"Created sync group: {db_group.name} ({db_group.id})")
    # Refresh to get associations
    db.refresh(db_group)
    response = SyncGroupResponse.model_validate(db_group)
    response.system_ids = group.system_ids
    return response


@router.get("/sync-groups", response_model=List[SyncGroupResponse])
async def list_sync_groups(skip: int = 0, limit: int = 100, db: Session = Depends(get_db)):
    """List all sync groups."""
    repo = SyncGroupRepository(db)
    groups = repo.get_all(skip=skip, limit=limit)
    responses = []
    for g in groups:
        response = SyncGroupResponse.model_validate(g)
        response.system_ids = [assoc.system_id for assoc in g.system_associations]
        responses.append(response)
    return responses


@router.get("/sync-groups/{group_id}", response_model=SyncGroupResponse)
async def get_sync_group(group_id: UUID, db: Session = Depends(get_db)):
    """Get a sync group by ID."""
    repo = SyncGroupRepository(db)
    group = repo.get(group_id)
    if not group:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Sync group not found")
    response = SyncGroupResponse.model_validate(group)
    response.system_ids = [assoc.system_id for assoc in group.system_associations]
    return response


@router.put("/sync-groups/{group_id}", response_model=SyncGroupResponse)
async def update_sync_group(
    group_id: UUID, group_update: SyncGroupUpdate, db: Session = Depends(get_db)
):
    """Update a sync group."""
    repo = SyncGroupRepository(db)
    update_data = group_update.model_dump(exclude_unset=True, exclude={"system_ids"}, by_alias=True)

    if update_data:
        group = repo.update(group_id, **update_data)
        if not group:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Sync group not found"
            )
    else:
        group = repo.get(group_id)
        if not group:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Sync group not found"
            )

    # Validate hub_system_id if directional update
    if group_update.system_ids is not None:
        # Check if the group is or will be directional
        is_directional = (
            group_update.directional if group_update.directional is not None else group.directional
        )
        hub_system_id = (
            group_update.hub_system_id
            if group_update.hub_system_id is not None
            else group.hub_system_id
        )

        if is_directional and hub_system_id and hub_system_id not in group_update.system_ids:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="hub_system_id must be one of the systems in the sync group",
            )

    # Update system associations if provided
    if group_update.system_ids is not None:
        # Remove existing associations
        from zfs_sync.database.models import SyncGroupSystemModel

        db.query(SyncGroupSystemModel).filter(
            SyncGroupSystemModel.sync_group_id == group_id
        ).delete()

        # Add new associations
        for system_id in group_update.system_ids:
            association = SyncGroupSystemModel(sync_group_id=group_id, system_id=system_id)
            db.add(association)

        db.commit()
        db.refresh(group)

    logger.info(f"Updated sync group: {group.name} ({group.id})")
    response = SyncGroupResponse.model_validate(group)
    response.system_ids = [assoc.system_id for assoc in group.system_associations]
    return response


@router.delete("/sync-groups/{group_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_sync_group(group_id: UUID, db: Session = Depends(get_db)):
    """Delete a sync group."""
    repo = SyncGroupRepository(db)
    if not repo.delete(group_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Sync group not found")
    logger.info(f"Deleted sync group: {group_id}")
