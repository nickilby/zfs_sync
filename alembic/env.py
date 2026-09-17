"""Alembic environment.

This file did not exist, which is why migrations have never run: without it
Alembic cannot resolve a connection or find the model metadata, so every
`alembic` invocation failed before it looked at a single revision. Schema was
in practice created by ``Base.metadata.create_all()``, which never alters an
existing table -- so deployments drifted away from the migrations that were
supposedly describing them.
"""

from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from zfs_sync.config import get_settings
from zfs_sync.database.base import Base

# Importing the models registers them on Base.metadata. Without this import
# autogenerate sees an empty schema and proposes dropping every table.
import zfs_sync.database.models  # noqa: F401

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def get_database_url() -> str:
    """Resolve the database URL.

    Precedence: an -x db_url override, then the application settings. The URL
    is not stored in alembic.ini so that migrations cannot be run against a
    different database than the service uses.
    """
    override = context.get_x_argument(as_dictionary=True).get("db_url")
    if override:
        return override
    return get_settings().database_url


def _is_sqlite(url: str) -> bool:
    return url.startswith("sqlite")


def run_migrations_offline() -> None:
    """Emit SQL to stdout without connecting."""
    url = get_database_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        # SQLite cannot ALTER or DROP most things in place; batch mode
        # recreates the table instead. Several existing migrations drop
        # columns and constraints, so without this they fail on the default
        # development database.
        render_as_batch=_is_sqlite(url),
        compare_type=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations against a live connection."""
    url = get_database_url()
    section = config.get_section(config.config_ini_section) or {}
    section["sqlalchemy.url"] = url

    connectable = engine_from_config(
        section,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            render_as_batch=_is_sqlite(url),
            compare_type=True,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
