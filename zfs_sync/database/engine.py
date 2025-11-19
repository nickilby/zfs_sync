"""Database engine creation and initialization."""

from sqlalchemy import create_engine as sa_create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import sessionmaker

from zfs_sync.config import get_settings
from zfs_sync.database.base import Base

SessionLocal = None


def create_engine() -> Engine:
    """Create and configure the database engine."""
    global SessionLocal

    settings = get_settings()
    engine = sa_create_engine(
        settings.database_url,
        connect_args={"check_same_thread": False} if "sqlite" in settings.database_url else {},
        echo=settings.debug,
    )

    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    return engine


def init_db() -> None:
    """Initialize the database by creating all tables."""
    engine = create_engine()
    Base.metadata.create_all(bind=engine)

