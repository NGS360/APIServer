"""add pipeline workflowregistration workflowrun samplesequencingrun tables and restructure workflow

Revision ID: 332d37fc6e64
Revises: 906fc3906e9d
Create Date: 2026-03-02 14:11:12.287216

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel
from sqlalchemy.dialects import mysql

# revision identifiers, used by Alembic.
revision: str = '332d37fc6e64'
down_revision: Union[str, Sequence[str], None] = '906fc3906e9d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # --- New tables ---
    op.create_table('platform',
        sa.Column('name', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.PrimaryKeyConstraint('name')
    )
    op.create_table('pipeline',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('name', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('version', sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('created_by', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_table('pipelineattribute',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('pipeline_id', sa.Uuid(), nullable=False),
        sa.Column('key', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('value', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.ForeignKeyConstraint(['pipeline_id'], ['pipeline.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('pipeline_id', 'key', name='uq_pipeline_attr_key')
    )
    op.create_table('pipelineworkflow',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('pipeline_id', sa.Uuid(), nullable=False),
        sa.Column('workflow_id', sa.Uuid(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('created_by', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.ForeignKeyConstraint(['pipeline_id'], ['pipeline.id']),
        sa.ForeignKeyConstraint(['workflow_id'], ['workflow.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('pipeline_id', 'workflow_id', name='uq_pipeline_workflow')
    )
    op.create_table('workflowregistration',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('workflow_id', sa.Uuid(), nullable=False),
        sa.Column('engine', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('external_id', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('created_by', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.ForeignKeyConstraint(['engine'], ['platform.name']),
        sa.ForeignKeyConstraint(['workflow_id'], ['workflow.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('workflow_id', 'engine', name='uq_workflow_engine')
    )
    op.create_table('workflowrun',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('workflow_id', sa.Uuid(), nullable=False),
        sa.Column('engine', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('external_run_id', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('created_by', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.ForeignKeyConstraint(['engine'], ['platform.name']),
        sa.ForeignKeyConstraint(['workflow_id'], ['workflow.id']),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_table('workflowrunattribute',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('workflow_run_id', sa.Uuid(), nullable=False),
        sa.Column('key', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('value', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.ForeignKeyConstraint(['workflow_run_id'], ['workflowrun.id']),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_table('samplesequencingrun',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('sample_id', sa.Uuid(), nullable=False),
        sa.Column('sequencing_run_id', sa.Uuid(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('created_by', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.ForeignKeyConstraint(['sample_id'], ['sample.id']),
        sa.ForeignKeyConstraint(['sequencing_run_id'], ['sequencingrun.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('sample_id', 'sequencing_run_id', name='uq_sample_seqrun')
    )

    # --- Add column to sequencingrun ---
    op.add_column('sequencingrun', sa.Column('sequencing_platform', sqlmodel.sql.sqltypes.AutoString(length=50), nullable=True))

    # --- Restructure workflow table ---
    # Add new columns (with server_default for existing rows)
    op.add_column('workflow', sa.Column('version', sqlmodel.sql.sqltypes.AutoString(), nullable=True))
    op.add_column('workflow', sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')))
    op.add_column('workflow', sa.Column('created_by', sqlmodel.sql.sqltypes.AutoString(), nullable=False, server_default=sa.text("'system'")))

    # Seed platform table from existing workflow engine values
    op.execute("""
        INSERT IGNORE INTO platform (name)
        SELECT DISTINCT engine FROM workflow
        WHERE engine IS NOT NULL
    """)

    # Migrate existing engine/engine_id data to workflowregistration
    # for any existing workflow rows that have engine data
    op.execute("""
        INSERT INTO workflowregistration
            (id, workflow_id, engine, external_id,
             created_at, created_by)
        SELECT UUID(), w.id, w.engine, w.engine_id,
               NOW(), 'migration'
        FROM workflow w
        WHERE w.engine IS NOT NULL
          AND w.engine_id IS NOT NULL
    """)

    # Remove old columns
    op.drop_column('workflow', 'engine_version')
    op.drop_column('workflow', 'engine')
    op.drop_column('workflow', 'engine_id')

    # Drop server defaults now that existing rows are backfilled
    op.alter_column('workflow', 'created_at', server_default=None)
    op.alter_column('workflow', 'created_by', server_default=None)


def downgrade() -> None:
    """Downgrade schema."""
    # --- Restore workflow columns ---
    op.add_column('workflow', sa.Column('engine_id', mysql.VARCHAR(length=255), nullable=True))
    op.add_column('workflow', sa.Column('engine', mysql.VARCHAR(length=255), nullable=True))
    op.add_column('workflow', sa.Column('engine_version', mysql.VARCHAR(length=255), nullable=True))

    # Migrate data back from workflowregistration to workflow
    # (pick first registration per workflow if multiple exist)
    op.execute("""
        UPDATE workflow w
        JOIN (
            SELECT workflow_id, engine, external_id
            FROM workflowregistration
            WHERE id IN (
                SELECT MIN(id) FROM workflowregistration GROUP BY workflow_id
            )
        ) wr ON w.id = wr.workflow_id
        SET w.engine = wr.engine,
            w.engine_id = wr.external_id
    """)

    # Make engine NOT NULL again after backfill
    op.alter_column('workflow', 'engine',
                     existing_type=mysql.VARCHAR(length=255),
                     nullable=False)

    op.drop_column('workflow', 'created_by')
    op.drop_column('workflow', 'created_at')
    op.drop_column('workflow', 'version')

    # --- Remove sequencingrun column ---
    op.drop_column('sequencingrun', 'sequencing_platform')

    # --- Drop new tables ---
    op.drop_table('workflowrunattribute')
    op.drop_table('samplesequencingrun')
    op.drop_table('workflowrun')
    op.drop_table('workflowregistration')
    op.drop_table('pipelineworkflow')
    op.drop_table('pipelineattribute')
    op.drop_table('pipeline')
    op.drop_table('platform')
