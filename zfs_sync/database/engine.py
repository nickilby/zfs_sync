"""Database engine creation and initialization."""

import os
from pathlib import Path

from sqlalchemy import create_engine as sa_create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import sessionmaker

from zfs_sync.config import get_settings
from zfs_sync.database.base import Base
from zfs_sync.logging_config import get_logger

logger = get_logger(__name__)

SessionLocal = None


def _ensure_database_directory(database_url: str) -> None:
    """
    Ensure the parent directory for SQLite database exists.

    SQLite doesn't create parent directories automatically, so we need to
    create them before attempting to create the database file.

    Args:
        database_url: SQLite database URL (e.g., 'sqlite:////path/to/db.db')

    Raises:
        OSError: If directory creation fails
        ValueError: If database URL format is invalid
    """
    if not database_url.startswith("sqlite:///"):
        # Not a SQLite database, no directory creation needed
        return

    # Extract file path from SQLite URL
    # sqlite:////absolute/path/to/db.db -> /absolute/path/to/db.db
    # sqlite:///relative/path/to/db.db -> relative/path/to/db.db
    file_path = database_url.replace("sqlite:///", "", 1)

    # Path() handles both forms identically:
    # sqlite:////path -> "/path" (absolute), sqlite:///path -> "path" (relative).
    db_path = Path(file_path)

    # Get parent directory
    parent_dir = db_path.parent

    # Create parent directory if it doesn't exist
    if parent_dir and not parent_dir.exists():
        try:
            parent_dir.mkdir(parents=True, exist_ok=True)
            logger.info(f"Created database directory: {parent_dir}")
        except OSError as e:
            error_msg = (
                f"Failed to create database directory '{parent_dir}': {e}. "
                f"Please ensure the parent directory exists and is writable, "
                f"or set ZFS_SYNC_DATABASE_URL to a path where the directory exists."
            )
            logger.error(error_msg)
            raise OSError(error_msg) from e

    # Verify the directory is writable
    if parent_dir.exists() and not os.access(parent_dir, os.W_OK):
        error_msg = (
            f"Database directory '{parent_dir}' is not writable. "
            f"Please check permissions (current user: {os.getuid() if hasattr(os, 'getuid') else 'unknown'})."
        )
        logger.error(error_msg)
        raise PermissionError(error_msg)


def create_engine() -> Engine:
    """
    Create and configure the database engine.

    For SQLite databases, ensures the parent directory exists before creating the engine.
    """
    global SessionLocal

    settings = get_settings()

    # Ensure database directory exists for SQLite databases
    try:
        _ensure_database_directory(settings.database_url)
    except (OSError, PermissionError) as e:
        logger.error(f"Database directory setup failed: {e}")
        raise

    engine = sa_create_engine(
        settings.database_url,
        connect_args={"check_same_thread": False} if "sqlite" in settings.database_url else {},
        echo=settings.debug,
    )

    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    return engine


def init_db() -> None:
    """
    Create the schema for a brand-new database, or verify an existing one.

    ``create_all()`` creates missing tables and never alters existing ones. It
    is therefore safe for an empty database and actively misleading for a
    populated one: it silently leaves a table that has drifted from the models
    exactly as it is. That is how deployments ended up without
    ``sync_groups.directional`` while the code branched on it, and how the
    migrations that described those changes were never applied to anything.

    So: an empty database is created and stamped at head, and a populated one
    is left alone with a warning if its schema does not match. Changing an
    existing schema is Alembic's job -- see docs/MIGRATION_RECOVERY.md.
    """
    # Import models to ensure they register with Base.metadata
    import zfs_sync.database.models  # noqa: F401

    settings = get_settings()

    # Ensure database directory exists (create_engine also does this, but be explicit)
    try:
        _ensure_database_directory(settings.database_url)
    except (OSError, PermissionError) as e:
        logger.error(f"Failed to prepare database directory: {e}")
        raise RuntimeError(f"Cannot initialize database: {e}") from e

    engine = create_engine()

    from sqlalchemy import inspect

    existing = set(inspect(engine).get_table_names())
    expected = set(Base.metadata.tables)

    if not existing - {"alembic_version"}:
        try:
            Base.metadata.create_all(bind=engine)
            logger.info("Created schema for a new database")
        except Exception as e:
            logger.error(f"Failed to create database tables: {e}")
            raise
        _stamp_head(engine)
        return

    missing = expected - existing
    if missing:
        logger.warning(
            "Database is missing table(s) %s. Not creating them: an existing "
            "database is migrated, not patched in place. Run 'alembic upgrade "
            "head' (see docs/MIGRATION_RECOVERY.md).",
            ", ".join(sorted(missing)),
        )
    else:
        logger.info("Database schema present (%d tables)", len(existing))


def _stamp_head(engine: Engine) -> None:
    """Record a freshly created database as being at the latest revision.

    Without this, the next ``alembic upgrade`` would try to replay revisions
    against a schema that already matches them.
    """
    try:
        from alembic import command
        from alembic.config import Config

        root = Path(__file__).resolve().parents[2]
        config = Config(str(root / "alembic.ini"))
        config.set_main_option("script_location", str(root / "alembic"))
        config.attributes["connection"] = engine
        command.stamp(config, "head")
        logger.info("Stamped new database at the latest migration revision")
    except Exception as e:  # stamping must never block startup
        logger.warning(
            "Could not stamp the new database at head (%s). Run "
            "'alembic stamp head' before the next upgrade.",
            e,
        )
