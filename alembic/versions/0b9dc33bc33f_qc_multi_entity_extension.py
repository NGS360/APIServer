"""qc multi-entity extension

Revision ID: 0b9dc33bc33f
Revises: 9427dcbe7514
Create Date: 2026-03-06 10:18:44.557720

Adds:
- qcrecord.workflow_run_id (nullable FK -> workflowrun.id) for provenance
- qcmetric.sequencing_run_id (nullable FK -> sequencingrun.id) for scoping
- qcmetric.workflow_run_id (nullable FK -> workflowrun.id) for scoping
- Indexes on all three new FK columns
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0b9dc33bc33f'
down_revision: Union[str, Sequence[str], None] = '9427dcbe7514'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add multi-entity FK columns to qcrecord and qcmetric."""
    # -- qcrecord: provenance link (which workflow run produced this)
    op.add_column(
        'qcrecord',
        sa.Column('workflow_run_id', sa.Uuid(), nullable=True),
    )
    op.create_index(
        op.f('ix_qcrecord_workflow_run_id'),
        'qcrecord', ['workflow_run_id'], unique=False,
    )
    op.create_foreign_key(
        'fk_qcrecord_workflow_run_id',
        'qcrecord', 'workflowrun',
        ['workflow_run_id'], ['id'],
    )

    # -- qcmetric: entity scoping (what this metric is *about*)
    op.add_column(
        'qcmetric',
        sa.Column('sequencing_run_id', sa.Uuid(), nullable=True),
    )
    op.add_column(
        'qcmetric',
        sa.Column('workflow_run_id', sa.Uuid(), nullable=True),
    )
    op.create_index(
        op.f('ix_qcmetric_sequencing_run_id'),
        'qcmetric', ['sequencing_run_id'], unique=False,
    )
    op.create_index(
        op.f('ix_qcmetric_workflow_run_id'),
        'qcmetric', ['workflow_run_id'], unique=False,
    )
    op.create_foreign_key(
        'fk_qcmetric_sequencing_run_id',
        'qcmetric', 'sequencingrun',
        ['sequencing_run_id'], ['id'],
    )
    op.create_foreign_key(
        'fk_qcmetric_workflow_run_id',
        'qcmetric', 'workflowrun',
        ['workflow_run_id'], ['id'],
    )


def downgrade() -> None:
    """Remove multi-entity FK columns from qcrecord and qcmetric."""
    # -- qcmetric: drop entity scoping columns
    op.drop_constraint(
        'fk_qcmetric_workflow_run_id', 'qcmetric',
        type_='foreignkey',
    )
    op.drop_constraint(
        'fk_qcmetric_sequencing_run_id', 'qcmetric',
        type_='foreignkey',
    )
    op.drop_index(
        op.f('ix_qcmetric_workflow_run_id'), table_name='qcmetric',
    )
    op.drop_index(
        op.f('ix_qcmetric_sequencing_run_id'), table_name='qcmetric',
    )
    op.drop_column('qcmetric', 'workflow_run_id')
    op.drop_column('qcmetric', 'sequencing_run_id')

    # -- qcrecord: drop provenance link
    op.drop_constraint(
        'fk_qcrecord_workflow_run_id', 'qcrecord',
        type_='foreignkey',
    )
    op.drop_index(
        op.f('ix_qcrecord_workflow_run_id'), table_name='qcrecord',
    )
    op.drop_column('qcrecord', 'workflow_run_id')
