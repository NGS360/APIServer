"""add sequencing_run_id to batchjob with backfill

Revision ID: a3c81f0d5e29
Revises: 236dab89760d
Create Date: 2026-09-03

Companion to 236dab89760d, which did the same for project_id. The two columns
are independent dimensions rather than alternatives: demultiplexing a flowcell
has a run and no project, a project-scoped pipeline job may carry both, and the
mirror of production shows 3,488 jobs that already have a project_id and also
name a run.

Historical rows are attributed by parsing the run out of the job name, which is
how the run page can be useful on the day it ships rather than only for jobs
submitted afterwards. Unlike the project backfill -- where the `projectid`
template variable reliably rendered the key into every job name -- demux job
names come from operator-authored YAML in S3, e.g.

    job_name: cellranger-mkfastq-{{ s3_run_folder_path.split('/')[-1] }}

so nothing *enforces* the convention. It holds well in practice: on the
production mirror 6,607 of 7,386 unattributed jobs resolve to a real run, with
zero jobs matching more than one run. The remainder are ONT runs whose run row
is gone and legacy junk names ('bcl2fastq-', 'bcl2fastq-Analysis'); those are
left NULL, since an unresolvable string would be worse than no attribution.
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
    """Add batchjob.sequencing_run_id, backfill it from job names, then index it."""
    op.add_column(
        'batchjob',
        sa.Column(
            'sequencing_run_id',
            sqlmodel.sql.sqltypes.AutoString(length=255),
            nullable=True,
        )
    )

    bind = op.get_bind()
    if bind.dialect.name == "mysql":
        # Join against sequencingrun so only ids that resolve to a real run are
        # written; the column has no FK, and an unresolvable string would be
        # worse than leaving the row unattributed.
        #
        # LIKE rather than a REGEXP as in 236dab89760d: run ids have no single
        # parseable shape (Illumina '260506_VH01208_93_222FCGLNX' and ONT
        # '20230922_2229_X1_FAW55684_0afany29' differ), so the run table itself
        # supplies the vocabulary. run_id is UNIQUE and long enough that no job
        # matched two runs across the whole production history.
        #
        # Deliberately not restricted to rows where project_id IS NULL: a job
        # can belong to both a project and a run, and this column is not a
        # fallback for the other.
        #
        # Backfilling before the index is created keeps this a single pass.
        result = bind.execute(sa.text("""
            UPDATE batchjob j
            JOIN sequencingrun r
              ON j.name LIKE CONCAT('%', r.run_id, '%')
            SET j.sequencing_run_id = r.run_id
        """))
        print(
            f"[{revision}] backfilled sequencing_run_id on "
            f"{result.rowcount} batchjob rows"
        )

    op.create_index(
        INDEX_NAME, 'batchjob', ['sequencing_run_id', 'submitted_on'], unique=False
    )


def downgrade() -> None:
    """Drop the index and the column; backfilled values are derived, not source data."""
    op.drop_index(INDEX_NAME, table_name='batchjob')
    op.drop_column('batchjob', 'sequencing_run_id')
