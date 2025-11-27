"""Add SSH fields to systems table

Revision ID: 001
Revises: 
Create Date: 2024-01-15 12:00:00.000000

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    """Add SSH connection fields to systems table."""
    op.add_column("systems", sa.Column("ssh_hostname", sa.String(255), nullable=True))
    op.add_column("systems", sa.Column("ssh_user", sa.String(100), nullable=True))
    op.add_column(
        "systems", sa.Column("ssh_port", sa.Integer(), nullable=False, server_default="22")
    )
    op.create_index(op.f("ix_systems_ssh_hostname"), "systems", ["ssh_hostname"], unique=False)


def downgrade():
    """Remove SSH connection fields from systems table."""
    op.drop_index(op.f("ix_systems_ssh_hostname"), table_name="systems")
    op.drop_column("systems", "ssh_port")
    op.drop_column("systems", "ssh_user")
    op.drop_column("systems", "ssh_hostname")
