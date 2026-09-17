"""Change sync_states to track datasets instead of snapshots

Revision ID: 003
Revises: 002
Create Date: 2024-11-28 10:00:00.000000

"""

from alembic import op
import sqlalchemy as sa

from zfs_sync.database.base import GUID


# revision identifiers, used by Alembic.
revision = "003"
down_revision = "002"
branch_labels = None
depends_on = None


def _drop_index_if_exists(index_name: str, table_name: str) -> None:
    """Drop an index only when the database actually has it.

    Deployments reached this schema through create_all() rather than through
    migrations, so which indexes exist varies. Checking is cheaper than a
    failed upgrade half way through.
    """
    inspector = sa.inspect(op.get_bind())
    existing = {index["name"] for index in inspector.get_indexes(table_name)}
    if index_name in existing:
        op.drop_index(index_name, table_name=table_name)


def upgrade():
    """Change sync_states table to use dataset instead of snapshot_id."""
    # sync_states is a current-status projection, not history, so clearing it
    # is safe: the scheduler repopulates it on its next pass.
    op.execute("DELETE FROM sync_states")

    # batch mode rebuilds the table on SQLite, which can neither drop a
    # constraint nor reliably drop a column in place. Dropping the column also
    # drops its foreign key on PostgreSQL, so no separate drop_constraint is
    # needed -- the previous explicit call named a PostgreSQL-style constraint
    # that does not exist on SQLite, and failed there.
    # Drop the index over snapshot_id first. Batch mode reflects the existing
    # table to rebuild it, so an index left in place would be recreated over a
    # column this migration has just removed.
    _drop_index_if_exists("ix_sync_states_snapshot_id", "sync_states")

    with op.batch_alter_table("sync_states") as batch_op:
        batch_op.drop_column("snapshot_id")
        batch_op.add_column(
            sa.Column("dataset", sa.String(255), nullable=False, server_default="")
        )

    op.create_index(op.f("ix_sync_states_dataset"), "sync_states", ["dataset"], unique=False)


def downgrade():
    """Revert sync_states table back to using snapshot_id."""
    op.drop_index(op.f("ix_sync_states_dataset"), table_name="sync_states")

    # sa.GUID does not exist -- SQLAlchemy has no such type, so this downgrade
    # raised AttributeError the moment it was reached. The project's own GUID
    # TypeDecorator is what the model uses.
    with op.batch_alter_table("sync_states") as batch_op:
        batch_op.drop_column("dataset")
        batch_op.add_column(sa.Column("snapshot_id", GUID(), nullable=True))
        batch_op.create_foreign_key(
            "sync_states_snapshot_id_fkey", "snapshots", ["snapshot_id"], ["id"]
        )
