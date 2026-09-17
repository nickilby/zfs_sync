"""Add directional sync fields to sync_groups table

Revision ID: 002_add_directional_sync_fields
Revises: 001_add_ssh_fields_to_systems
Create Date: 2025-12-02 00:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from zfs_sync.database.base import GUID

# revision identifiers, used by Alembic.
revision: str = "004"
down_revision: Union[str, None] = "003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add directional sync fields to sync_groups table."""
    # batch_alter_table rebuilds the table on SQLite, which cannot add a
    # foreign key to an existing one; on PostgreSQL it is a plain ALTER.
    with op.batch_alter_table("sync_groups") as batch_op:
        # Defaults to False: existing groups keep bidirectional behaviour.
        batch_op.add_column(
            # sa.false() renders per dialect. A literal "false" string writes
            # the text 'false' on SQLite, which Python then reads back as a
            # truthy non-empty string -- so every existing group would look
            # directional after this migration.
            sa.Column("directional", sa.Boolean(), nullable=False, server_default=sa.false())
        )
        # Nullable; only meaningful when directional is true.
        batch_op.add_column(sa.Column("hub_system_id", GUID(), nullable=True))
        batch_op.create_foreign_key(
            "fk_sync_groups_hub_system_id",
            "systems",
            ["hub_system_id"],
            ["id"],
            ondelete="SET NULL",
        )

    op.create_index("ix_sync_groups_hub_system_id", "sync_groups", ["hub_system_id"])


def downgrade() -> None:
    """Remove directional sync fields from sync_groups table."""
    op.drop_index("ix_sync_groups_hub_system_id", table_name="sync_groups")

    with op.batch_alter_table("sync_groups") as batch_op:
        batch_op.drop_constraint("fk_sync_groups_hub_system_id", type_="foreignkey")
        batch_op.drop_column("hub_system_id")
        batch_op.drop_column("directional")
