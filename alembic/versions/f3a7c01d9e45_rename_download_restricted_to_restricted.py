"""Rename project.download_restricted to project.restricted

Revision ID: f3a7c01d9e45
Revises: d5e8a3f9b1c2
Create Date: 2026-10-08

The flag was added in c9f4b7e28a13 for downloads alone. It now marks a project
locked down for *every* action -- any project-scoped write, not just fetching
bytes -- so the narrower name had become actively misleading about what setting
it does.

A rename rather than a second column, because the two would never legitimately
disagree: a project whose data may not be downloaded but may be deleted is not
a coherent state, and carrying both would invite exactly that.

Safe to rename rather than deprecate: the column is set on **0 of 11,156**
projects in production, so there is no data to migrate and no caller depending
on the old behaviour. It does change the API shape -- `download_restricted`
becomes `restricted` on ProjectPublic and ProjectUpdate -- which is a breaking
change in principle. In practice nothing sets it, and the frontend does not read
it.

MySQL rewrites nothing for a column rename; it is a metadata operation.
"""
from alembic import op
import sqlalchemy as sa


revision = 'f3a7c01d9e45'
down_revision = 'd5e8a3f9b1c2'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        'project',
        'download_restricted',
        new_column_name='restricted',
        existing_type=sa.Boolean(),
        existing_nullable=False,
        existing_server_default=sa.false(),
    )


def downgrade() -> None:
    op.alter_column(
        'project',
        'restricted',
        new_column_name='download_restricted',
        existing_type=sa.Boolean(),
        existing_nullable=False,
        existing_server_default=sa.false(),
    )
