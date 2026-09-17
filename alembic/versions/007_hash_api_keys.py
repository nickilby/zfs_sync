"""Hash API keys in place

Revision ID: 007
Revises: 006
Create Date: 2026-09-17 00:00:00.000000

API keys were stored in plaintext and compared by equality. Combined with the
response schema exposing the column, an unauthenticated ``GET /systems``
returned every key in the fleet.

Because the plaintext is present in the database, it can be hashed here and no
client needs a new key -- every system keeps working with the key it already
holds. That is the whole reason this migration is worth running rather than
forcing a fleet-wide rotation.

The digest is SHA-256, not a password KDF: these are 32 bytes of
``secrets.token_urlsafe`` entropy, so there is no dictionary to attack, and the
digest is checked on every authenticated request.

Downgrading cannot restore the plaintext -- that is the point -- so it clears
the column and the affected systems must be issued new keys.
"""

import hashlib
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "007"
down_revision: Union[str, None] = "006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

PREFIX_LENGTH = 8


def upgrade() -> None:
    # Plain ADD COLUMN, not batch mode: batch rebuilds the table from the
    # current model, which no longer declares api_key -- and the plaintext in
    # that column is what this migration needs to read.
    op.add_column("systems", sa.Column("api_key_hash", sa.String(64), nullable=True))
    op.add_column("systems", sa.Column("api_key_prefix", sa.String(16), nullable=True))

    bind = op.get_bind()
    rows = bind.execute(
        sa.text("SELECT id, api_key FROM systems WHERE api_key IS NOT NULL")
    ).fetchall()

    for system_id, api_key in rows:
        bind.execute(
            sa.text(
                "UPDATE systems SET api_key_hash = :digest, api_key_prefix = :prefix "
                "WHERE id = :id"
            ),
            {
                "digest": hashlib.sha256(api_key.encode("utf-8")).hexdigest(),
                "prefix": api_key[:PREFIX_LENGTH],
                "id": system_id,
            },
        )

    if rows:
        print(f"  hashed {len(rows)} API key(s) in place; no client needs a new key")

    # SQLite refuses to drop a column an index still references, so the old
    # index goes first. Which indexes exist varies, because deployments
    # reached this schema through create_all() rather than migrations.
    inspector = sa.inspect(bind)
    existing_indexes = {index["name"] for index in inspector.get_indexes("systems")}
    if "ix_systems_api_key" in existing_indexes:
        op.drop_index("ix_systems_api_key", table_name="systems")

    # No batch mode. A unique index is how SQLAlchemy renders unique=True on
    # this column anyway, and unlike a table constraint it can be created in
    # place on both backends.
    op.drop_column("systems", "api_key")
    op.create_index("ix_systems_api_key_hash", "systems", ["api_key_hash"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_systems_api_key_hash", table_name="systems")

    # A digest cannot be reversed, so every system is left without a key and
    # must be issued a new one.
    op.add_column("systems", sa.Column("api_key", sa.String(255), nullable=True))
    op.drop_column("systems", "api_key_prefix")
    op.drop_column("systems", "api_key_hash")
    op.create_index("ix_systems_api_key", "systems", ["api_key"], unique=True)
