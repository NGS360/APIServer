"""qc multi-entity extension + run-scoped QCRecords (Phase 3 + 3b)

Revision ID: 0b9dc33bc33f
Revises: 9427dcbe7514
Create Date: 2026-03-06 10:18:44.557720

Phase 3 — Multi-entity extension:
- qcrecord.project_id FK constraint -> project.project_id (RESTRICT on delete)
- qcrecord.workflow_run_id (nullable FK -> workflowrun.id) for provenance
- qcmetric.sequencing_run_id (nullable FK -> sequencingrun.id) for scoping
- qcmetric.workflow_run_id (nullable FK -> workflowrun.id) for scoping

Phase 3b — Run-scoped QCRecords:
- qcrecord.project_id: NOT NULL -> nullable (run-scoped records have no project)
- qcrecord.sequencing_run_id (nullable FK -> sequencingrun.id) for run-scoped records
- CHECK constraint: exactly one of project_id / sequencing_run_id must be non-NULL
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
    """Add multi-entity FKs and run-scoped support to qcrecord/qcmetric."""
    # ── Phase 3: Multi-entity extension ───────────────────────────────

    # -- qcrecord: enforce project_id FK (column + index already exist)
    op.create_foreign_key(
        'fk_qcrecord_project_id',
        'qcrecord', 'project',
        ['project_id'], ['project_id'],
        ondelete='RESTRICT',
    )

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

    # ── Phase 3b: Run-scoped QCRecords ────────────────────────────────

    # -- qcrecord.project_id: make nullable (run-scoped records have no project)
    op.alter_column(
        'qcrecord',
        'project_id',
        existing_type=sa.String(50),
        nullable=True,
    )

    # -- qcrecord.sequencing_run_id: run-scoped subject FK
    op.add_column(
        'qcrecord',
        sa.Column('sequencing_run_id', sa.Uuid(), nullable=True),
    )
    op.create_index(
        op.f('ix_qcrecord_sequencing_run_id'),
        'qcrecord', ['sequencing_run_id'], unique=False,
    )
    op.create_foreign_key(
        'fk_qcrecord_sequencing_run_id',
        'qcrecord', 'sequencingrun',
        ['sequencing_run_id'], ['id'],
    )

    # -- CHECK: exactly one of project_id / sequencing_run_id must be set
    op.execute(
        sa.text(
            "ALTER TABLE qcrecord ADD CONSTRAINT "
            "ck_qcrecord_scope CHECK ("
            "(project_id IS NOT NULL AND sequencing_run_id IS NULL) OR "
            "(project_id IS NULL AND sequencing_run_id IS NOT NULL)"
            ")"
        )
    )


def downgrade() -> None:
    """Remove multi-entity FKs and run-scoped support."""
    # ── Phase 3b rollback ─────────────────────────────────────────────

    # -- Drop CHECK constraint
    op.execute(
        sa.text(
            "ALTER TABLE qcrecord DROP CONSTRAINT "
            "IF EXISTS ck_qcrecord_scope"
        )
    )

    # -- Drop sequencing_run_id column from qcrecord
    op.drop_constraint(
        'fk_qcrecord_sequencing_run_id', 'qcrecord',
        type_='foreignkey',
    )
    op.drop_index(
        op.f('ix_qcrecord_sequencing_run_id'), table_name='qcrecord',
    )
    op.drop_column('qcrecord', 'sequencing_run_id')

    # -- Make project_id NOT NULL again (delete any run-scoped records first)
    op.execute(
        sa.text(
            "DELETE FROM qcrecord WHERE project_id IS NULL"
        )
    )
    op.alter_column(
        'qcrecord',
        'project_id',
        existing_type=sa.String(50),
        nullable=False,
    )

    # ── Phase 3 rollback ──────────────────────────────────────────────

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
        'fk_qcrecord_project_id', 'qcrecord',
        type_='foreignkey',
    )
    op.drop_constraint(
        'fk_qcrecord_workflow_run_id', 'qcrecord',
        type_='foreignkey',
    )
    op.drop_index(
        op.f('ix_qcrecord_workflow_run_id'), table_name='qcrecord',
    )
    op.drop_column('qcrecord', 'workflow_run_id')
