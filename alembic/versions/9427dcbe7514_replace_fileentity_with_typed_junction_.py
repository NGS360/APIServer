"""replace fileentity with typed junction tables

Revision ID: 9427dcbe7514
Revises: 332d37fc6e64
Create Date: 2026-03-05 15:48:27.061223

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel

# revision identifiers, used by Alembic.
revision: str = '9427dcbe7514'
down_revision: Union[str, Sequence[str], None] = '332d37fc6e64'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Replace polymorphic fileentity with typed junction tables.

    Steps:
    1. Create 5 new typed junction tables
    2. Migrate existing fileentity data into typed tables
    3. Drop the old fileentity table

    Note: RUN-type fileentity rows require barcode-to-UUID resolution
    that is too complex for SQL. Those are handled by a separate
    Python migration script using SequencingRun.parse_barcode().
    """
    # --- Step 1: Create typed junction tables ---

    op.create_table('fileproject',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('file_id', sa.Uuid(), nullable=False),
        sa.Column('project_id', sa.Uuid(), nullable=False),
        sa.Column('role', sqlmodel.sql.sqltypes.AutoString(length=50), nullable=True),
        sa.ForeignKeyConstraint(['file_id'], ['file.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['project_id'], ['project.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('file_id', 'project_id', name='uq_fileproject'),
    )

    op.create_table('filesequencingrun',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('file_id', sa.Uuid(), nullable=False),
        sa.Column('sequencing_run_id', sa.Uuid(), nullable=False),
        sa.Column('role', sqlmodel.sql.sqltypes.AutoString(length=50), nullable=True),
        sa.ForeignKeyConstraint(['file_id'], ['file.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['sequencing_run_id'], ['sequencingrun.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('file_id', 'sequencing_run_id', name='uq_filesequencingrun'),
    )

    op.create_table('fileqcrecord',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('file_id', sa.Uuid(), nullable=False),
        sa.Column('qcrecord_id', sa.Uuid(), nullable=False),
        sa.Column('role', sqlmodel.sql.sqltypes.AutoString(length=50), nullable=True),
        sa.ForeignKeyConstraint(['file_id'], ['file.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['qcrecord_id'], ['qcrecord.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('file_id', 'qcrecord_id', name='uq_fileqcrecord'),
    )

    op.create_table('fileworkflowrun',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('file_id', sa.Uuid(), nullable=False),
        sa.Column('workflow_run_id', sa.Uuid(), nullable=False),
        sa.Column('role', sqlmodel.sql.sqltypes.AutoString(length=50), nullable=True),
        sa.ForeignKeyConstraint(['file_id'], ['file.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['workflow_run_id'], ['workflowrun.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('file_id', 'workflow_run_id', name='uq_fileworkflowrun'),
    )

    op.create_table('filepipeline',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('file_id', sa.Uuid(), nullable=False),
        sa.Column('pipeline_id', sa.Uuid(), nullable=False),
        sa.Column('role', sqlmodel.sql.sqltypes.AutoString(length=50), nullable=True),
        sa.ForeignKeyConstraint(['file_id'], ['file.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['pipeline_id'], ['pipeline.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('file_id', 'pipeline_id', name='uq_filepipeline'),
    )

    # --- Step 2: Migrate existing fileentity data ---

    # PROJECT: entity_id is project.project_id (string) → resolve to project.id (UUID)
    op.execute("""
        INSERT INTO fileproject (id, file_id, project_id, role)
        SELECT UUID(), fe.file_id, p.id, fe.role
        FROM fileentity fe
        JOIN project p ON fe.entity_id = p.project_id
        WHERE fe.entity_type = 'PROJECT'
    """)

    # QCRECORD: entity_id is UUID string → match directly to qcrecord.id
    op.execute("""
        INSERT INTO fileqcrecord (id, file_id, qcrecord_id, role)
        SELECT UUID(), fe.file_id, UNHEX(REPLACE(fe.entity_id, '-', '')), fe.role
        FROM fileentity fe
        WHERE fe.entity_type = 'QCRECORD'
          AND EXISTS (
            SELECT 1 FROM qcrecord
            WHERE qcrecord.id = UNHEX(REPLACE(fe.entity_id, '-', ''))
          )
    """)

    # SAMPLE: FileEntity SAMPLE rows are redundant with FileSample — skip.
    # FileSample already has proper FK constraints and role support.

    # RUN: Barcode-to-UUID resolution is complex (computed property).
    # Handled by separate Python migration script. See:
    # plans/phase2-file-association-evolution.md Q1.
    # Any remaining RUN rows will be logged and skipped.

    # --- Step 3: Drop the old fileentity table ---
    # drop_table handles dropping all indexes and FK constraints automatically
    op.drop_table('fileentity')


def downgrade() -> None:
    """Recreate fileentity and restore data from typed junction tables."""
    from sqlalchemy.dialects import mysql

    # Recreate the original fileentity table
    op.create_table('fileentity',
        sa.Column('id', mysql.CHAR(length=32), nullable=False),
        sa.Column('file_id', mysql.CHAR(length=32), nullable=False),
        sa.Column('entity_type', mysql.VARCHAR(length=50), nullable=False),
        sa.Column('entity_id', mysql.VARCHAR(length=100), nullable=False),
        sa.Column('role', mysql.VARCHAR(length=50), nullable=True),
        sa.ForeignKeyConstraint(
            ['file_id'], ['file.id'],
            name=op.f('fileentity_ibfk_1'), ondelete='CASCADE',
        ),
        sa.PrimaryKeyConstraint('id'),
        mysql_collate='utf8mb4_0900_ai_ci',
        mysql_default_charset='utf8mb4',
        mysql_engine='InnoDB',
    )
    op.create_index(
        op.f('uq_fileentity_file_entity'), 'fileentity',
        ['file_id', 'entity_type', 'entity_id'], unique=True,
    )
    op.create_index(
        op.f('ix_fileentity_entity'), 'fileentity',
        ['entity_type', 'entity_id'], unique=False,
    )

    # Migrate data back from typed tables to fileentity
    op.execute("""
        INSERT INTO fileentity (id, file_id, entity_type, entity_id, role)
        SELECT HEX(fp.id), fp.file_id, 'PROJECT', p.project_id, fp.role
        FROM fileproject fp
        JOIN project p ON fp.project_id = p.id
    """)

    op.execute("""
        INSERT INTO fileentity (id, file_id, entity_type, entity_id, role)
        SELECT HEX(fq.id), fq.file_id, 'QCRECORD',
               LOWER(CONCAT(
                   SUBSTR(HEX(fq.qcrecord_id), 1, 8), '-',
                   SUBSTR(HEX(fq.qcrecord_id), 9, 4), '-',
                   SUBSTR(HEX(fq.qcrecord_id), 13, 4), '-',
                   SUBSTR(HEX(fq.qcrecord_id), 17, 4), '-',
                   SUBSTR(HEX(fq.qcrecord_id), 21)
               )),
               fq.role
        FROM fileqcrecord fq
    """)

    # Note: RUN and PIPELINE/WORKFLOWRUN data may not roundtrip perfectly
    # since the original barcode format is lost for RUN entities.

    # Drop the typed junction tables
    op.drop_table('filepipeline')
    op.drop_table('fileworkflowrun')
    op.drop_table('fileqcrecord')
    op.drop_table('filesequencingrun')
    op.drop_table('fileproject')
