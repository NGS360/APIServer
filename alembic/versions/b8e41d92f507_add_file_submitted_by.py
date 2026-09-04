"""Add file.submitted_by, the authenticated caller who registered a file

Revision ID: b8e41d92f507
Revises: f7a2c9e14b60
Create Date: 2026-09-05

`file.created_by` is client-supplied, and production shows it is used honestly as
an *on behalf of* claim rather than abused: 39,459 rows carry a username, every
one resolves to a real account, all of them arrive with `source = 'NGS360_demux'`,
and of the 42 people named, only 2 hold an API key. One pipeline registers files
for 40 scientists who have no credential of their own.

So the field cannot also carry accountability -- the person named is usually not
the person who called. An earlier attempt overwrote `created_by` with the
authenticated caller, which would have replaced 42 named scientists with a
service key's owner. This column is the other half instead: who actually made the
request, set server-side, never accepted from a client.

Nullable and not backfilled. For rows written before this existed the submitter is
genuinely unknown, and `source` already records the submitting *system* for the
attributed ones. Inventing a principal from a system name would put a value in an
accountability column that nobody actually asserted, which is worse than null.

Adding a nullable column with no default is metadata-only in MySQL 8 -- no table
rebuild, no lock held over 634k rows.
"""
from alembic import op
import sqlalchemy as sa


revision = 'b8e41d92f507'
down_revision = 'f7a2c9e14b60'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        'file',
        sa.Column('submitted_by', sa.String(length=100), nullable=True),
    )


def downgrade() -> None:
    op.drop_column('file', 'submitted_by')
