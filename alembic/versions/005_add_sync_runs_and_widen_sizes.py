"""Add sync_runs history and widen snapshot size columns

Revision ID: 005
Revises: 004
Create Date: 2026-09-17 00:00:00.000000

Two unrelated but overdue schema facts:

* ``sync_runs`` records reported execution outcomes. Until the feedback loop
  existed the witness issued commands and never learned whether they worked,
  so there was nothing to store.
* ``snapshots.size``/``referenced``/``used`` were ``Integer``, which is four
  bytes on PostgreSQL and overflows above about 2.1 GB -- an ordinary snapshot
  size. SQLite was unaffected (it stores integers as up to eight bytes
  regardless of the declared type), which is why this went unnoticed in
  development.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

from zfs_sync.database.base import GUID

revision: str = "005"
down_revision: Union[str, None] = "004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "sync_runs",
        sa.Column("id", GUID(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("sync_group_id", GUID(), nullable=False),
        sa.Column("dataset", sa.String(255), nullable=False),
        sa.Column("source_system_id", GUID(), nullable=False),
        sa.Column("target_system_id", GUID(), nullable=False),
        sa.Column("starting_snapshot", sa.String(255), nullable=True),
        sa.Column("ending_snapshot", sa.String(255), nullable=True),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("duration_seconds", sa.Integer(), nullable=True),
        sa.Column("bytes_transferred", sa.BigInteger(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("reported_by_system_id", GUID(), nullable=True),
        sa.Column("metadata", sa.JSON(), nullable=True),
        sa.ForeignKeyConstraint(["sync_group_id"], ["sync_groups.id"]),
        sa.ForeignKeyConstraint(["source_system_id"], ["systems.id"]),
        sa.ForeignKeyConstraint(["target_system_id"], ["systems.id"]),
        sa.ForeignKeyConstraint(["reported_by_system_id"], ["systems.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_sync_runs_sync_group_id", "sync_runs", ["sync_group_id"])
    op.create_index("ix_sync_runs_dataset", "sync_runs", ["dataset"])
    op.create_index("ix_sync_runs_source_system_id", "sync_runs", ["source_system_id"])
    op.create_index("ix_sync_runs_target_system_id", "sync_runs", ["target_system_id"])
    op.create_index("ix_sync_runs_status", "sync_runs", ["status"])
    op.create_index("ix_sync_runs_reported_by_system_id", "sync_runs", ["reported_by_system_id"])

    # SQLite stores integers as up to eight bytes whatever the column says, so
    # this widening is a no-op there and a real change on PostgreSQL.
    with op.batch_alter_table("snapshots") as batch_op:
        batch_op.alter_column(
            "size", existing_type=sa.Integer(), type_=sa.BigInteger(), existing_nullable=True
        )
        batch_op.alter_column(
            "referenced",
            existing_type=sa.Integer(),
            type_=sa.BigInteger(),
            existing_nullable=True,
        )
        batch_op.alter_column(
            "used", existing_type=sa.Integer(), type_=sa.BigInteger(), existing_nullable=True
        )


def downgrade() -> None:
    # Narrowing back to Integer will fail on PostgreSQL if any stored value
    # exceeds 2^31, which is the whole reason for the widening. That is
    # intentional: losing a real size is worse than a refused downgrade.
    with op.batch_alter_table("snapshots") as batch_op:
        batch_op.alter_column(
            "used", existing_type=sa.BigInteger(), type_=sa.Integer(), existing_nullable=True
        )
        batch_op.alter_column(
            "referenced",
            existing_type=sa.BigInteger(),
            type_=sa.Integer(),
            existing_nullable=True,
        )
        batch_op.alter_column(
            "size", existing_type=sa.BigInteger(), type_=sa.Integer(), existing_nullable=True
        )

    op.drop_index("ix_sync_runs_reported_by_system_id", table_name="sync_runs")
    op.drop_index("ix_sync_runs_status", table_name="sync_runs")
    op.drop_index("ix_sync_runs_target_system_id", table_name="sync_runs")
    op.drop_index("ix_sync_runs_source_system_id", table_name="sync_runs")
    op.drop_index("ix_sync_runs_dataset", table_name="sync_runs")
    op.drop_index("ix_sync_runs_sync_group_id", table_name="sync_runs")
    op.drop_table("sync_runs")
