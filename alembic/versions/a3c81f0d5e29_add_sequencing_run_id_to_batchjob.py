"""add sequencing_run_id to batchjob

Revision ID: a3c81f0d5e29
Revises: 236dab89760d
Create Date: 2026-09-03

Companion to 236dab89760d, which did the same for project_id. The two columns
are independent dimensions rather than alternatives: demultiplexing a flowcell
has a run and no project, a project-scoped pipeline job may carry both, and the
mirror of production shows 3,488 jobs that already have a project_id and also
name a run.

Schema only -- attribution of historical rows is a separate step, unlike
236dab89760d which backfills inline. The difference is the cost of recognising
the key in a job name. A project id has a fixed shape, so 236dab89760d pulls it
out with REGEXP_SUBSTR and joins on project's indexed key: 24,921 rows in 3.2s
on the staging mirror. Run ids have no single shape (Illumina
'260506_VH01208_93_222FCGLNX' and ONT '20230922_2229_X1_FAW55684_0afany29'
differ), so the only way to recognise one is to match against the run table
itself, and `name LIKE CONCAT('%', run_id, '%')` is not indexable. Measured on
the same mirror: 10,095 rows in 4m13s, EXPLAIN showing a full scan of batchjob
nested against every sequencingrun row through the join buffer -- roughly 212M
substring comparisons.

entrypoint.sh runs `alembic upgrade head` with `set -e` before exec'ing uvicorn,
so that time is time the container serves no traffic. Four minutes of it risks
an Elastic Beanstalk health-check timeout on deploy, and alembic takes no MySQL
lock, so two instances starting together would both run it. Hence:

    PYTHONPATH=. python3 scripts/backfill_batchjob_sequencing_run_id.py

which is restartable, chunked, and safe to run against a live database. The
column is nullable with no foreign key, so the application is correct while it
is still NULL -- a run's job list is simply shorter until the backfill has run.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel


# revision identifiers, used by Alembic.
revision: str = 'a3c81f0d5e29'
down_revision: Union[str, Sequence[str], None] = '236dab89760d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Mirrors ix_batchjob_project_id_submitted_on: every read is "jobs for run X,
# newest first", and covering the sort avoids a filesort over the wide command
# column.
INDEX_NAME = 'ix_batchjob_sequencing_run_id_submitted_on'


def upgrade() -> None:
    """Add batchjob.sequencing_run_id and index it. No data is written."""
    op.add_column(
        'batchjob',
        sa.Column(
            'sequencing_run_id',
            sqlmodel.sql.sqltypes.AutoString(length=255),
            nullable=True,
        )
    )
    op.create_index(
        INDEX_NAME, 'batchjob', ['sequencing_run_id', 'submitted_on'], unique=False
    )


def downgrade() -> None:
    """Drop the index and the column; any backfilled values are derived, not source data."""
    op.drop_index(INDEX_NAME, table_name='batchjob')
    op.drop_column('batchjob', 'sequencing_run_id')
