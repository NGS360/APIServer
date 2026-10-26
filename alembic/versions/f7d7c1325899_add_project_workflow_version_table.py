"""Add the projectworkflowversion table

Revision ID: f7d7c1325899
Revises: c8e4a1f72b93
Create Date: 2026-10-23

Records which version of each workflow a project runs on an engine, so a
project keeps running the same version across runs, even after an alias moves.
A row is created on a project's first run, from an alias or an explicit version;
PUT creates or overwrites it.

`version` is stored as the version number with a composite FK to
workflowversion(workflow_id, version), rather than an FK to workflowversion.id:
the number is what GA4GH WES takes (`<workflow_id>:<version>`), and the FK still
stops a recorded version from being deleted. MySQL needs the referenced columns
indexed, which the existing uq_workflow_version unique key already provides.

UNIQUE(project_id, workflow_id, engine) is what makes the first-run insert safe
when two callers resolve the same project at once: one insert wins and the
other re-reads that row.

New table only; no existing rows are touched.
"""
from typing import Sequence, Union

import sqlalchemy as sa
import sqlmodel
from alembic import op

revision: str = 'f7d7c1325899'
down_revision: Union[str, Sequence[str], None] = 'c8e4a1f72b93'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'projectworkflowversion',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('project_id', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('workflow_id', sa.Uuid(), nullable=False),
        sa.Column('version', sa.Integer(), nullable=False),
        sa.Column('engine', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('created_by', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.Column('updated_by', sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['project_id'], ['project.project_id']),
        sa.ForeignKeyConstraint(['workflow_id'], ['workflow.id']),
        sa.ForeignKeyConstraint(['engine'], ['platform.name']),
        sa.ForeignKeyConstraint(
            ['workflow_id', 'version'],
            ['workflowversion.workflow_id', 'workflowversion.version'],
            name='fk_projectworkflowversion_workflowversion',
        ),
        sa.UniqueConstraint(
            'project_id', 'workflow_id', 'engine', name='uq_project_workflow_engine',
        ),
    )


def downgrade() -> None:
    op.drop_table('projectworkflowversion')
