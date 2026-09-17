"""Add project.download_restricted

Revision ID: c9f4b7e28a13
Revises: b8e41d92f507
Create Date: 2026-09-09

Downloads became open-by-default on 2026-09-09 (see docs/RBAC.md, "Downloads:
open by default, restricted by exception"). A project may opt out, and this is
the opt-out.

Default false, and **not** backfilled to anything else, which is the whole point
of the policy: every existing project becomes open. That is a deliberate,
reviewed loosening rather than an oversight -- the previous default-deny model
would have refused a legitimate 33M-request genomics workload across 66 projects
unless someone maintained 66 project memberships for it.

`server_default` is set as well as the Python-side default so that the 5,000-odd
existing rows get a concrete value rather than NULL. A nullable boolean would
make "not restricted" and "never considered" the same state, and this column is
precisely the one where that distinction should not be lost.

Adding a column with a default is metadata-only in MySQL 8 -- no table rebuild.
"""
from alembic import op
import sqlalchemy as sa


revision = 'c9f4b7e28a13'
down_revision = 'b8e41d92f507'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        'project',
        sa.Column(
            'download_restricted',
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )


def downgrade() -> None:
    op.drop_column('project', 'download_restricted')
