"""Initial schema

Revision ID: 000
Revises:
Create Date: 2026-09-17 00:00:00.000000

The baseline the other revisions assumed but never provided.

Migrations 001 onward call ``op.add_column("systems", ...)`` and friends, so
they only work against a database where those tables already exist. Nothing
created them: ``Base.metadata.create_all()`` did that at runtime, which is why
`alembic upgrade head` against an empty database failed on the first revision
and why the migration chain was never exercised end to end.

This revision creates the schema as it stood *before* revision 001, so the
chain runs from nothing to head. It deliberately reproduces the old shape --
``sync_states.snapshot_id``, ``Integer`` snapshot sizes, ``sync_groups``
without ``description`` or the directional columns -- because the later
revisions are what change them.

An existing database created by ``create_all()`` should not run this revision.
See docs/MIGRATION_RECOVERY.md for how to stamp such a database at the right
point instead.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

from zfs_sync.database.base import GUID

revision: str = "000"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _timestamps() -> list:
    """The created_at/updated_at pair every table inherits from BaseModel."""
    return [
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    ]


def upgrade() -> None:
    op.create_table(
        "systems",
        sa.Column("id", GUID(), nullable=False),
        *_timestamps(),
        sa.Column("hostname", sa.String(255), nullable=False),
        sa.Column("platform", sa.String(50), nullable=False),
        sa.Column("connectivity_status", sa.String(20), nullable=False, server_default="unknown"),
        sa.Column("last_seen", sa.DateTime(timezone=True), nullable=True),
        sa.Column("api_key", sa.String(255), nullable=True),
        sa.Column("metadata", sa.JSON(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_systems_hostname", "systems", ["hostname"], unique=True)
    op.create_index("ix_systems_api_key", "systems", ["api_key"], unique=True)

    op.create_table(
        "snapshots",
        sa.Column("id", GUID(), nullable=False),
        *_timestamps(),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("pool", sa.String(100), nullable=False),
        sa.Column("dataset", sa.String(255), nullable=False),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
        # Widened to BigInteger in revision 005.
        sa.Column("size", sa.Integer(), nullable=True),
        sa.Column("referenced", sa.Integer(), nullable=True),
        sa.Column("used", sa.Integer(), nullable=True),
        sa.Column("system_id", GUID(), nullable=False),
        sa.Column("metadata", sa.JSON(), nullable=True),
        sa.ForeignKeyConstraint(["system_id"], ["systems.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_snapshots_name", "snapshots", ["name"])
    op.create_index("ix_snapshots_pool", "snapshots", ["pool"])
    op.create_index("ix_snapshots_dataset", "snapshots", ["dataset"])
    op.create_index("ix_snapshots_timestamp", "snapshots", ["timestamp"])
    op.create_index("ix_snapshots_system_id", "snapshots", ["system_id"])

    op.create_table(
        "sync_groups",
        sa.Column("id", GUID(), nullable=False),
        *_timestamps(),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("sync_interval_seconds", sa.Integer(), nullable=False, server_default="3600"),
        sa.Column("metadata", sa.JSON(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_sync_groups_name", "sync_groups", ["name"], unique=True)

    op.create_table(
        "sync_group_systems",
        sa.Column("id", GUID(), nullable=False),
        *_timestamps(),
        sa.Column("sync_group_id", GUID(), nullable=False),
        sa.Column("system_id", GUID(), nullable=False),
        sa.ForeignKeyConstraint(["sync_group_id"], ["sync_groups.id"]),
        sa.ForeignKeyConstraint(["system_id"], ["systems.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_sync_group_systems_sync_group_id", "sync_group_systems", ["sync_group_id"]
    )
    op.create_index("ix_sync_group_systems_system_id", "sync_group_systems", ["system_id"])

    op.create_table(
        "sync_states",
        sa.Column("id", GUID(), nullable=False),
        *_timestamps(),
        sa.Column("sync_group_id", GUID(), nullable=False),
        # Replaced by `dataset` in revision 003.
        sa.Column("snapshot_id", GUID(), nullable=False),
        sa.Column("system_id", GUID(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="out_of_sync"),
        sa.Column("last_sync", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_check", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("metadata", sa.JSON(), nullable=True),
        sa.ForeignKeyConstraint(["sync_group_id"], ["sync_groups.id"]),
        sa.ForeignKeyConstraint(["snapshot_id"], ["snapshots.id"]),
        sa.ForeignKeyConstraint(["system_id"], ["systems.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_sync_states_sync_group_id", "sync_states", ["sync_group_id"])
    op.create_index("ix_sync_states_snapshot_id", "sync_states", ["snapshot_id"])
    op.create_index("ix_sync_states_system_id", "sync_states", ["system_id"])
    op.create_index("ix_sync_states_status", "sync_states", ["status"])


def downgrade() -> None:
    op.drop_table("sync_states")
    op.drop_table("sync_group_systems")
    op.drop_table("sync_groups")
    op.drop_table("snapshots")
    op.drop_table("systems")
