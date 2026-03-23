"""add workflow version and alias tables

Revision ID: 908e88cdaf0e
Revises: 0706aaf19b43
Create Date: 2026-03-23 14:25:38.423849

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel
from sqlalchemy.dialects import mysql

# revision identifiers, used by Alembic.
revision: str = '908e88cdaf0e'
down_revision: Union[str, Sequence[str], None] = '0706aaf19b43'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""

    # 1. Create new tables
    op.create_table(
        'workflowversion',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('workflow_id', sa.Uuid(), nullable=False),
        sa.Column(
            'version',
            sqlmodel.sql.sqltypes.AutoString(), nullable=False,
        ),
        sa.Column(
            'definition_uri',
            sqlmodel.sql.sqltypes.AutoString(), nullable=False,
        ),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column(
            'created_by',
            sqlmodel.sql.sqltypes.AutoString(), nullable=False,
        ),
        sa.ForeignKeyConstraint(['workflow_id'], ['workflow.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint(
            'workflow_id', 'version', name='uq_workflow_version',
        ),
    )
    op.create_table(
        'workflowversionalias',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('workflow_id', sa.Uuid(), nullable=False),
        sa.Column(
            'alias',
            sqlmodel.sql.sqltypes.AutoString(), nullable=False,
        ),
        sa.Column('workflow_version_id', sa.Uuid(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column(
            'created_by',
            sqlmodel.sql.sqltypes.AutoString(), nullable=False,
        ),
        sa.ForeignKeyConstraint(['workflow_id'], ['workflow.id']),
        sa.ForeignKeyConstraint(
            ['workflow_version_id'], ['workflowversion.id'],
        ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint(
            'workflow_id', 'alias', name='uq_workflow_alias',
        ),
    )

    # 2. Migrate existing workflow rows into workflowversion.
    #    For each workflow with a definition_uri, create a version row.
    #    MySQL 8.0 provides UUID() which returns a 36-char hyphenated UUID.
    op.execute("""
        INSERT INTO workflowversion (
            id, workflow_id, version, definition_uri,
            created_at, created_by
        )
        SELECT
            UUID(),
            id,
            COALESCE(version, '0.0.0'),
            definition_uri,
            created_at,
            created_by
        FROM workflow
        WHERE definition_uri IS NOT NULL
    """)

    # 3. Re-point workflowregistration: workflow_id → workflow_version_id
    #    Add as NULLABLE first, populate, then make NOT NULL.
    op.add_column(
        'workflowregistration',
        sa.Column('workflow_version_id', sa.Uuid(), nullable=True),
    )
    op.execute("""
        UPDATE workflowregistration wr
        JOIN workflowversion wv ON wv.workflow_id = wr.workflow_id
        SET wr.workflow_version_id = wv.id
    """)
    op.alter_column(
        'workflowregistration', 'workflow_version_id',
        existing_type=sa.Uuid(), nullable=False,
    )
    # Must drop FK before dropping the index it references (MySQL)
    op.drop_constraint(
        'workflowregistration_ibfk_2',
        'workflowregistration', type_='foreignkey',
    )
    op.drop_index(
        'uq_workflow_engine', table_name='workflowregistration',
    )
    op.create_unique_constraint(
        'uq_workflowversion_engine',
        'workflowregistration',
        ['workflow_version_id', 'engine'],
    )
    op.create_foreign_key(
        'fk_wfreg_workflowversion',
        'workflowregistration', 'workflowversion',
        ['workflow_version_id'], ['id'],
    )
    op.drop_column('workflowregistration', 'workflow_id')

    # 4. Re-point workflowrun: workflow_id → workflow_version_id
    op.add_column(
        'workflowrun',
        sa.Column('workflow_version_id', sa.Uuid(), nullable=True),
    )
    op.execute("""
        UPDATE workflowrun wr
        JOIN workflowversion wv ON wv.workflow_id = wr.workflow_id
        SET wr.workflow_version_id = wv.id
    """)
    op.alter_column(
        'workflowrun', 'workflow_version_id',
        existing_type=sa.Uuid(), nullable=False,
    )
    op.drop_constraint(
        op.f('workflowrun_ibfk_2'),
        'workflowrun', type_='foreignkey',
    )
    op.create_foreign_key(
        'fk_wfrun_workflowversion',
        'workflowrun', 'workflowversion',
        ['workflow_version_id'], ['id'],
    )
    op.drop_column('workflowrun', 'workflow_id')

    # 5. Drop version and definition_uri from workflow (data is now in
    #    workflowversion)
    op.drop_column('workflow', 'definition_uri')
    op.drop_column('workflow', 'version')


def downgrade() -> None:
    """Downgrade schema."""

    # 1. Re-add version and definition_uri to workflow
    op.add_column(
        'workflow',
        sa.Column('version', mysql.VARCHAR(length=255), nullable=True),
    )
    op.add_column(
        'workflow',
        sa.Column(
            'definition_uri', mysql.VARCHAR(length=255), nullable=True,
        ),
    )
    # Restore from workflowversion (pick the earliest version per workflow)
    op.execute("""
        UPDATE workflow w
        JOIN (
            SELECT wv1.workflow_id,
                   wv1.version,
                   wv1.definition_uri
            FROM workflowversion wv1
            INNER JOIN (
                SELECT workflow_id, MIN(created_at) AS min_created
                FROM workflowversion
                GROUP BY workflow_id
            ) wv2 ON wv1.workflow_id = wv2.workflow_id
                  AND wv1.created_at = wv2.min_created
        ) wv ON wv.workflow_id = w.id
        SET w.version = wv.version,
            w.definition_uri = wv.definition_uri
    """)

    # 2. Restore workflowrun.workflow_id
    op.add_column(
        'workflowrun',
        sa.Column('workflow_id', mysql.CHAR(length=32), nullable=True),
    )
    op.execute("""
        UPDATE workflowrun wr
        JOIN workflowversion wv ON wv.id = wr.workflow_version_id
        SET wr.workflow_id = wv.workflow_id
    """)
    op.alter_column(
        'workflowrun', 'workflow_id',
        existing_type=mysql.CHAR(length=32), nullable=False,
    )
    op.drop_constraint(
        'fk_wfrun_workflowversion', 'workflowrun', type_='foreignkey',
    )
    op.create_foreign_key(
        op.f('workflowrun_ibfk_2'),
        'workflowrun', 'workflow', ['workflow_id'], ['id'],
    )
    op.drop_column('workflowrun', 'workflow_version_id')

    # 3. Restore workflowregistration.workflow_id
    op.add_column(
        'workflowregistration',
        sa.Column('workflow_id', mysql.CHAR(length=32), nullable=True),
    )
    op.execute("""
        UPDATE workflowregistration wr
        JOIN workflowversion wv ON wv.id = wr.workflow_version_id
        SET wr.workflow_id = wv.workflow_id
    """)
    op.alter_column(
        'workflowregistration', 'workflow_id',
        existing_type=mysql.CHAR(length=32), nullable=False,
    )
    op.drop_constraint(
        'fk_wfreg_workflowversion',
        'workflowregistration', type_='foreignkey',
    )
    op.create_foreign_key(
        op.f('workflowregistration_ibfk_2'),
        'workflowregistration', 'workflow', ['workflow_id'], ['id'],
    )
    op.drop_constraint(
        'uq_workflowversion_engine',
        'workflowregistration', type_='unique',
    )
    op.create_index(
        op.f('uq_workflow_engine'),
        'workflowregistration', ['workflow_id', 'engine'], unique=True,
    )
    op.drop_column('workflowregistration', 'workflow_version_id')

    # 4. Drop new tables
    op.drop_table('workflowversionalias')
    op.drop_table('workflowversion')
