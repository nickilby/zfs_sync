"""Base database models and session management."""

from sqlalchemy import Column, DateTime, String
from sqlalchemy.dialects.postgresql import UUID as PostgresUUID
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import Session
from sqlalchemy.sql import func
from sqlalchemy.types import TypeDecorator, CHAR
import uuid

Base = declarative_base()

# SessionLocal will be set by engine module
SessionLocal = None


class GUID(TypeDecorator):
    """Platform-independent GUID type for SQLAlchemy."""

    impl = CHAR
    cache_ok = True

    def load_dialect_impl(self, dialect):
        if dialect.name == 'postgresql':
            return dialect.type_descriptor(PostgresUUID())
        else:
            return dialect.type_descriptor(CHAR(36))

    def process_bind_param(self, value, dialect):
        if value is None:
            return value
        elif dialect.name == 'postgresql':
            return str(value)
        else:
            if not isinstance(value, uuid.UUID):
                return str(uuid.UUID(value))
            return str(value)

    def process_result_value(self, value, dialect):
        if value is None:
            return value
        else:
            if not isinstance(value, uuid.UUID):
                return uuid.UUID(value)
            return value


class BaseModel(Base):
    """Base model with common fields."""

    __abstract__ = True

    id = Column(GUID(), primary_key=True, default=uuid.uuid4)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


def get_session() -> Session:
    """Get a database session."""
    from zfs_sync.database.engine import SessionLocal as _SessionLocal

    if _SessionLocal is None:
        from zfs_sync.database.engine import create_engine

        create_engine()
        from zfs_sync.database.engine import SessionLocal as _SessionLocal

    return _SessionLocal()


def get_db():
    """Dependency for FastAPI to get database session."""
    db = get_session()
    try:
        yield db
    finally:
        db.close()

