"""repair invalid project zero dates

Revision ID: a16a32f14864
Revises: 49e7d06e7eb4
Create Date: 2026-07-01 09:55:24.089679

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel


# revision identifiers, used by Alembic.
revision: str = 'a16a32f14864'
down_revision: Union[str, Sequence[str], None] = '49e7d06e7eb4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Fallback timestamp matches the convention used by the original backfill
# migration (49e7d06e7eb4) for rows whose date could not be determined.
FALLBACK = '1970-01-01 00:00:00'


def upgrade() -> None:
    """
    Repair invalid "zero dates" left behind by the backfill in 49e7d06e7eb4.

    A project_id such as 'P-10000001-####' parsed via STR_TO_DATE produced
    '1000-00-01' (month/day 0), which MySQL stored instead of returning NULL.
    Those values crash datetime validation when reading projects, so reset
    them to the same fallback used elsewhere for unknown dates.
    """
    bind = op.get_bind()
    if bind.dialect.name != "mysql":
        # Migration set is MySQL-targeted; nothing to repair on other engines.
        return

    for column in ("created_at", "last_modified"):
        bind.execute(sa.text(f"""
            UPDATE project
            SET {column} = :fallback
            WHERE {column} IS NULL
               OR YEAR({column}) < 1970
               OR MONTH({column}) = 0
               OR DAY({column}) = 0
        """), {"fallback": FALLBACK})


def downgrade() -> None:
    """Downgrade schema.

    Data repair is not reversible; the original invalid values are not
    recoverable, so this is intentionally a no-op.
    """
    pass
