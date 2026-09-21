"""Add workflowversion.inputs and .outputs JSON columns

Revision ID: d5e8a3f9b1c2
Revises: c9f4b7e28a13
Create Date: 2026-09-21

Two nullable JSON columns hold the workflow's declared input and output
parameter schemas. Nullable is deliberate: existing rows have no schema
recorded and won't be backfilled. Populated at version-create time only;
inputs/outputs are immutable once set.

Adding nullable JSON columns is metadata-only in MySQL 8 — no table rebuild.
"""
from alembic import op
import sqlalchemy as sa


revision = 'd5e8a3f9b1c2'
down_revision = 'c9f4b7e28a13'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        'workflowversion',
        sa.Column('inputs', sa.JSON(), nullable=True),
    )
    op.add_column(
        'workflowversion',
        sa.Column('outputs', sa.JSON(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column('workflowversion', 'outputs')
    op.drop_column('workflowversion', 'inputs')
