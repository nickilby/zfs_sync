"""Base repository class with common CRUD operations."""

from typing import Generic, List, Optional, Type, TypeVar
from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from zfs_sync.database.base import BaseModel
from zfs_sync.logging_config import get_logger

logger = get_logger(__name__)

ModelType = TypeVar("ModelType", bound=BaseModel)


class BaseRepository(Generic[ModelType]):
    """Base repository with common CRUD operations."""

    def __init__(self, model: Type[ModelType], db: Session):
        """Initialize repository with model and database session."""
        self.model = model
        self.db = db

    def get(self, id: UUID) -> Optional[ModelType]:
        """Get a record by ID."""
        return self.db.query(self.model).filter(self.model.id == id).first()

    def get_all(self, skip: int = 0, limit: int = 100) -> List[ModelType]:
        """Get all records with pagination."""
        return self.db.query(self.model).offset(skip).limit(limit).all()

    def create(self, **kwargs) -> ModelType:
        """
        Create a new record.

        Raises:
            ValueError: If a unique constraint violation occurs
            Exception: For other database errors
        """
        try:
            db_obj = self.model(**kwargs)
            self.db.add(db_obj)
            self.db.commit()
            self.db.refresh(db_obj)
            return db_obj
        except IntegrityError as e:
            self.db.rollback()
            error_msg = str(e.orig) if hasattr(e, "orig") else str(e)
            logger.error(f"Database integrity error creating {self.model.__name__}: {error_msg}")
            raise ValueError(
                f"Failed to create {self.model.__name__}: constraint violation. "
                f"Details: {error_msg}"
            ) from e
        except Exception as e:
            self.db.rollback()
            logger.error(f"Database error creating {self.model.__name__}: {e}")
            raise

    def update(self, id: UUID, **kwargs) -> Optional[ModelType]:
        """
        Update a record by ID.

        Raises:
            ValueError: If a unique constraint violation occurs
            Exception: For other database errors
        """
        db_obj = self.get(id)
        if db_obj:
            try:
                for key, value in kwargs.items():
                    setattr(db_obj, key, value)
                self.db.commit()
                self.db.refresh(db_obj)
            except IntegrityError as e:
                self.db.rollback()
                error_msg = str(e.orig) if hasattr(e, "orig") else str(e)
                logger.error(
                    f"Database integrity error updating {self.model.__name__} {id}: {error_msg}"
                )
                raise ValueError(
                    f"Failed to update {self.model.__name__} {id}: constraint violation. "
                    f"Details: {error_msg}"
                ) from e
            except Exception as e:
                self.db.rollback()
                logger.error(f"Database error updating {self.model.__name__} {id}: {e}")
                raise
        return db_obj

    def delete(self, id: UUID) -> bool:
        """
        Delete a record by ID.

        Raises:
            Exception: For database errors
        """
        db_obj = self.get(id)
        if db_obj:
            try:
                self.db.delete(db_obj)
                self.db.commit()
                return True
            except Exception as e:
                self.db.rollback()
                logger.error(f"Database error deleting {self.model.__name__} {id}: {e}")
                raise
        return False
