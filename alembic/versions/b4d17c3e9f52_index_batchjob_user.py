"""index batchjob.user

Revision ID: b4d17c3e9f52
Revises: d5e8a3f9b1c2
Create Date: 2026-10-06

The Submitted By filter on the jobs tables pages through
`GROUP BY user ORDER BY COUNT(*) DESC`, narrowing by a LIKE on the username as
the caller types. Without an index on `user` that aggregate is a full scan:
EXPLAIN on the staging mirror reports type=ALL over 33,823 rows with
"Using temporary; Using filesort", at 20ms unscoped. Tolerable once per page
load, which is what the first cut of the filter did; not once per keystroke,
which is what paging and type-to-filter make it.

With the index the same query reports type=index, key=ix_batchjob_user and
"Using index" -- an index-only scan that no longer reads the table, whose
`command` column is up to 1000 characters. 20ms -> 7.4ms unscoped, and
12ms -> 6.8ms for a LIKE-narrowed keystroke. The temporary table and filesort
remain: the ordering is by COUNT(*), which no index can satisfy.

The project and run scopes already have composite indexes that narrow before
the aggregate runs, so this is for the unscoped admin case, where there is no
other key to use.

Index only, no backfill, so `alembic upgrade head` in entrypoint.sh stays fast
-- unlike 236dab89760d, this adds no deploy-blocking work.
"""
from alembic import op


# revision identifiers, used by Alembic.
revision = 'b4d17c3e9f52'
down_revision = 'd5e8a3f9b1c2'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index('ix_batchjob_user', 'batchjob', ['user'], unique=False)


def downgrade() -> None:
    op.drop_index('ix_batchjob_user', table_name='batchjob')
