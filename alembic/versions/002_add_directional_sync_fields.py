"""Add directional sync fields to sync_groups table

Revision ID: 002_add_directional_sync_fields
Revises: 001_add_ssh_fields_to_systems
Create Date: 2025-12-02 00:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "002_add_directional_sync_fields"
down_revision: Union[str, None] = "001_add_ssh_fields_to_systems"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add directional sync fields to sync_groups table."""
    # Add directional column (defaults to False for bidirectional behavior)
    op.add_column(
        "sync_groups",
        sa.Column("directional", sa.Boolean(), nullable=False, server_default="false"),
    )

    # Add hub_system_id column (nullable, only used when directional=True)
    op.add_column(
        "sync_groups", sa.Column("hub_system_id", postgresql.UUID(as_uuid=True), nullable=True)
    )

    # Add foreign key constraint for hub_system_id
    op.create_foreign_key(
        "fk_sync_groups_hub_system_id",
        "sync_groups",
        "systems",
        ["hub_system_id"],
        ["id"],
        ondelete="SET NULL",
    )

    # Add index for hub_system_id for performance
    op.create_index("ix_sync_groups_hub_system_id", "sync_groups", ["hub_system_id"])


def downgrade() -> None:
    """Remove directional sync fields from sync_groups table."""
    # Remove index
    op.drop_index("ix_sync_groups_hub_system_id", table_name="sync_groups")

    # Remove foreign key constraint
    op.drop_constraint("fk_sync_groups_hub_system_id", "sync_groups", type_="foreignkey")

    # Remove columns
    op.drop_column("sync_groups", "hub_system_id")
    op.drop_column("sync_groups", "directional")
