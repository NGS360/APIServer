"""Enforce case-insensitive attribute keys

Attribute tables (sampleattribute, projectattribute, ...) rely on a
``UniqueConstraint(entity_id, key)`` to prevent duplicate keys. That constraint
is only case-insensitive when the ``key`` column carries a case-insensitive
collation, so on some deployments ``SOURCE_URI`` and ``source_uri`` could be
stored as two separate rows. This pins the ``key`` columns to the case-insensitive
``utf8mb4_0900_ai_ci`` collation so the guarantee holds everywhere, and adds the
unique constraints that were missing on the two workflow attribute tables.

IMPORTANT: run ``scripts/dedupe_attribute_case.py`` (without ``--dry-run``) first.
This migration's ALTERs and unique-index creation will fail while case-only
duplicate keys still exist.

Revision ID: e5c9d1a4b8f2
Revises: d7e3f9a2b1c4
Create Date: 2026-07-22 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e5c9d1a4b8f2'
down_revision: Union[str, Sequence[str], None] = 'd7e3f9a2b1c4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


CI_COLLATION = "utf8mb4_0900_ai_ci"

# (table, column) pairs whose key must be case-insensitive. FileTag.key is
# VARCHAR(255); the SQLModel AutoString columns also render as VARCHAR(255).
KEY_COLUMNS = [
    ("sampleattribute", "key"),
    ("projectattribute", "key"),
    ("pipelineattribute", "key"),
    ("workflowattribute", "key"),
    ("workflowversionattribute", "key"),
    ("filetag", "key"),
]

# Unique constraints missing on the workflow attribute tables. The FK column is
# recorded too: MySQL uses the unique index to back the foreign key on that
# column, so downgrade must add a plain index on it before dropping the unique
# constraint (otherwise error 1553: "needed in a foreign key constraint").
WORKFLOW_UNIQUE_CONSTRAINTS = [
    (
        "workflowattribute",
        "uq_workflow_attr_key",
        ["workflow_id", "key"],
        "workflow_id",
    ),
    (
        "workflowversionattribute",
        "uq_workflowversion_attr_key",
        ["workflow_version_id", "key"],
        "workflow_version_id",
    ),
]


def upgrade() -> None:
    """Upgrade schema."""
    bind = op.get_bind()
    if bind.dialect.name != "mysql":
        # Collation is a MySQL concern; fresh non-MySQL DBs get the unique
        # constraints from the model definitions at create-table time.
        return

    for table, column in KEY_COLUMNS:
        # ``key`` is a reserved word in MySQL, so identifiers are backtick-quoted.
        bind.execute(sa.text(
            f"ALTER TABLE `{table}` "
            f"MODIFY `{column}` VARCHAR(255) "
            f"CHARACTER SET utf8mb4 COLLATE {CI_COLLATION} NOT NULL"
        ))

    for table, name, columns, _fk_col in WORKFLOW_UNIQUE_CONSTRAINTS:
        op.create_unique_constraint(name, table, columns)


def downgrade() -> None:
    """Downgrade schema.

    Drops the added workflow unique constraints. The collation change is left
    in place — it is non-destructive and reverting it could reintroduce the
    duplicate-key hazard.
    """
    bind = op.get_bind()
    if bind.dialect.name != "mysql":
        return

    for table, name, _columns, fk_col in WORKFLOW_UNIQUE_CONSTRAINTS:
        # Add a plain index on the FK column first so the foreign key stays
        # indexed once the unique constraint is dropped (MySQL error 1553).
        index_name = f"ix_{table}_{fk_col}"
        op.create_index(index_name, table, [fk_col])
        op.drop_constraint(name, table, type_="unique")
