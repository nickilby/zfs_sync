"""Deduplicate and add natural-key uniqueness

Revision ID: 006
Revises: 005
Create Date: 2026-09-17 00:00:00.000000

Two tables had no uniqueness on the key that identifies a row.

``snapshots``: clients report their entire inventory on every polling cycle,
and ingestion called ``create()`` unconditionally with no upsert. Every cycle
therefore multiplied the rows, and the duplicates then skewed every "latest
snapshot" comparison built on them -- ``max(..., key=timestamp)`` picks an
arbitrary row among ties.

``sync_states``: ``update_sync_state`` does a get-then-create, which races.

Existing duplicates are removed before the constraints are applied, keeping the
most recently created row of each group. For snapshots that is safe by
definition: duplicates are repeated reports of the same snapshot, so they carry
the same facts.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "006"
down_revision: Union[str, None] = "005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _deduplicate(table: str, key_columns: Sequence[str]) -> int:
    """Delete all but the newest row for each distinct key.

    Uses a correlated subquery rather than a window function so that it works
    on older SQLite builds as well as PostgreSQL.
    """
    bind = op.get_bind()
    keys = ", ".join(key_columns)
    match = " AND ".join(
        f"(dupe.{column} = target.{column} OR "
        f"(dupe.{column} IS NULL AND target.{column} IS NULL))"
        for column in key_columns
    )

    result = bind.execute(
        sa.text(
            f"""
            DELETE FROM {table}
            WHERE id IN (
                SELECT dupe.id FROM {table} AS dupe
                WHERE EXISTS (
                    SELECT 1 FROM {table} AS target
                    WHERE {match}
                      AND (target.created_at > dupe.created_at
                           OR (target.created_at = dupe.created_at
                               AND target.id > dupe.id))
                )
            )
            """  # noqa: S608 - table and column names are literals in this module
        )
    )
    removed = result.rowcount or 0
    if removed:
        print(f"  removed {removed} duplicate row(s) from {table} (key: {keys})")
    return removed


def upgrade() -> None:
    _deduplicate("snapshots", ["system_id", "pool", "dataset", "name"])
    _deduplicate("sync_states", ["sync_group_id", "dataset", "system_id"])

    with op.batch_alter_table("snapshots") as batch_op:
        batch_op.create_unique_constraint(
            "uq_snapshot_identity", ["system_id", "pool", "dataset", "name"]
        )

    with op.batch_alter_table("sync_states") as batch_op:
        batch_op.create_unique_constraint(
            "uq_sync_state_pair", ["sync_group_id", "dataset", "system_id"]
        )


def downgrade() -> None:
    with op.batch_alter_table("sync_states") as batch_op:
        batch_op.drop_constraint("uq_sync_state_pair", type_="unique")

    with op.batch_alter_table("snapshots") as batch_op:
        batch_op.drop_constraint("uq_snapshot_identity", type_="unique")
