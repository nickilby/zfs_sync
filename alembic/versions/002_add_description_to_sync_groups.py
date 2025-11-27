"""Add description field to sync_groups table

Revision ID: 002
Revises: 001
Create Date: 2024-11-26 14:00:00.000000

"""

# pylint: disable=no-member
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "002"
down_revision = "001"
branch_labels = None
depends_on = None


def upgrade():
    """Add description field to sync_groups table."""
    op.add_column("sync_groups", sa.Column("description", sa.Text(), nullable=True))


def downgrade():
    """Remove description field from sync_groups table."""
    op.drop_column("sync_groups", "description")
