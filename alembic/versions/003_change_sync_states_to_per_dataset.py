"""Change sync_states to track datasets instead of snapshots

Revision ID: 003
Revises: 002
Create Date: 2024-11-28 10:00:00.000000

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "003"
down_revision = "002"
branch_labels = None
depends_on = None


def upgrade():
    """Change sync_states table to use dataset instead of snapshot_id."""
    # Drop the foreign key constraint first
    op.drop_constraint("sync_states_snapshot_id_fkey", "sync_states", type_="foreignkey")

    # Drop the snapshot_id column
    op.drop_column("sync_states", "snapshot_id")

    # Add dataset column
    op.add_column(
        "sync_states", sa.Column("dataset", sa.String(255), nullable=False, server_default="")
    )

    # Create index on dataset
    op.create_index(op.f("ix_sync_states_dataset"), "sync_states", ["dataset"], unique=False)


def downgrade():
    """Revert sync_states table back to using snapshot_id."""
    # Drop the dataset index
    op.drop_index(op.f("ix_sync_states_dataset"), table_name="sync_states")

    # Drop the dataset column
    op.drop_column("sync_states", "dataset")

    # Add snapshot_id column back (nullable for migration, but should be populated)
    op.add_column("sync_states", sa.Column("snapshot_id", sa.GUID(), nullable=True))

    # Recreate foreign key constraint
    op.create_foreign_key(
        "sync_states_snapshot_id_fkey", "sync_states", "snapshots", ["snapshot_id"], ["id"]
    )
