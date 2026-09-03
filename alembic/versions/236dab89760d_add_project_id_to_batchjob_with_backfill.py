"""add project_id to batchjob with backfill

Revision ID: 236dab89760d
Revises: f7a2c9e14b60
Create Date: 2026-08-28 17:40:36.188055

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel


# revision identifiers, used by Alembic.
revision: str = '236dab89760d'
down_revision: Union[str, Sequence[str], None] = 'f7a2c9e14b60'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Project business keys look like P-YYYYMMDD-NNNN. The three project-aware
# submission paths render this into the job name via the Jinja2 `projectid`
# template variable, so historical rows can be attributed by parsing it back
# out. Legacy 3-digit-suffix ids (P-20200917-003) exist in old job names but
# have no matching project row, so the stricter 4-digit pattern is used and the
# join below discards anything that does not resolve.
PROJECT_ID_PATTERN = 'P-[0-9]{8}-[0-9]{4}'

# Composite rather than an index on project_id alone: every read is "jobs for
# project X, newest first", and covering the sort avoids a filesort over the
# wide command column.
INDEX_NAME = 'ix_batchjob_project_id_submitted_on'


def upgrade() -> None:
    """Add batchjob.project_id, backfill it from job names, then index it."""
    op.add_column(
        'batchjob',
        sa.Column('project_id', sqlmodel.sql.sqltypes.AutoString(length=255), nullable=True)
    )

    bind = op.get_bind()
    if bind.dialect.name == "mysql":
        # Join against project so only ids that resolve to a real project are
        # written; the column has no FK, and an unresolvable string would be
        # worse than leaving the row unattributed.
        #
        # Backfilling before the index is created keeps this a single pass.
        # Name and command always agree where both carry an id, so parsing the
        # (much shorter, always-present) name is sufficient.
        result = bind.execute(sa.text(f"""
            UPDATE batchjob j
            JOIN project p
              ON p.project_id = REGEXP_SUBSTR(j.name, '{PROJECT_ID_PATTERN}')
            SET j.project_id = p.project_id
            WHERE j.name REGEXP '{PROJECT_ID_PATTERN}'
        """))
        print(f"[{revision}] backfilled project_id on {result.rowcount} batchjob rows")

    op.create_index(INDEX_NAME, 'batchjob', ['project_id', 'submitted_on'], unique=False)


def downgrade() -> None:
    """Drop the index and the column; backfilled values are derived, not source data."""
    op.drop_index(INDEX_NAME, table_name='batchjob')
    op.drop_column('batchjob', 'project_id')
