"""Base repository class with common CRUD operations."""

from typing import Generic, List, Optional, Type, TypeVar
from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from zfs_sync.database.base import BaseModel
from zfs_sync.database.errors import classify_integrity_error
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
            DuplicateRecord: If the row already exists.
            InvalidReference: If a foreign key points at a missing row.
            ConstraintViolation: For any other integrity failure.
        """
        try:
            db_obj = self.model(**kwargs)
            self.db.add(db_obj)
            self.db.commit()
            self.db.refresh(db_obj)
            return db_obj
        except IntegrityError as e:
            self.db.rollback()
            # Classify rather than collapsing everything into one error: a
            # duplicate and a dangling reference need different HTTP statuses
            # and different fixes.
            error = classify_integrity_error(e, self.model.__name__)
            logger.warning("Integrity error creating %s: %s", self.model.__name__, error.detail)
            raise error from e
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
                error = classify_integrity_error(e, self.model.__name__)
                logger.warning(
                    "Integrity error updating %s %s: %s",
                    self.model.__name__,
                    id,
                    error.detail,
                )
                raise error from e
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
