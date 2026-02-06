"""Add QCMetrics and migrate File to unified schema

Revision ID: f1a2b3c4d5e6
Revises: b6847b89d202
Create Date: 2026-01-29 16:45:00.000000

This migration:
1. Transforms the existing `file` table to the new unified schema
2. Creates supporting tables (fileentity, filehash, filetag, filesample)
3. Migrates existing data from old columns to new structure
4. Creates the QCRecord tables for QCMetrics
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel


# revision identifiers, used by Alembic.
revision: str = 'f1a2b3c4d5e6'
down_revision: Union[str, Sequence[str], None] = 'b6847b89d202'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Migrate file table to unified schema and create QCMetrics tables."""

    # ========================================================================
    # Step 1: Create new supporting tables for File
    # ========================================================================

    # fileentity - many-to-many junction for file-entity associations
    op.create_table(
        'fileentity',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('file_id', sa.Uuid(), nullable=False),
        sa.Column(
            'entity_type',
            sqlmodel.sql.sqltypes.AutoString(length=50),
            nullable=False
        ),
        sa.Column(
            'entity_id',
            sqlmodel.sql.sqltypes.AutoString(length=100),
            nullable=False
        ),
        sa.Column(
            'role',
            sqlmodel.sql.sqltypes.AutoString(length=50),
            nullable=True
        ),
        sa.ForeignKeyConstraint(['file_id'], ['file.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint(
            'file_id', 'entity_type', 'entity_id',
            name='uq_fileentity_file_entity'
        )
    )
    op.create_index(
        'ix_fileentity_entity',
        'fileentity',
        ['entity_type', 'entity_id']
    )

    # filehash - hash values for files
    op.create_table(
        'filehash',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('file_id', sa.Uuid(), nullable=False),
        sa.Column(
            'algorithm',
            sqlmodel.sql.sqltypes.AutoString(length=50),
            nullable=False
        ),
        sa.Column(
            'value',
            sqlmodel.sql.sqltypes.AutoString(length=128),
            nullable=False
        ),
        sa.ForeignKeyConstraint(['file_id'], ['file.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint(
            'file_id', 'algorithm',
            name='uq_filehash_file_algorithm'
        )
    )

    # filetag - key-value tags for files
    op.create_table(
        'filetag',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('file_id', sa.Uuid(), nullable=False),
        sa.Column(
            'key',
            sqlmodel.sql.sqltypes.AutoString(length=255),
            nullable=False
        ),
        sa.Column('value', sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(['file_id'], ['file.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('file_id', 'key', name='uq_filetag_file_key')
    )

    # filesample - sample associations for files
    op.create_table(
        'filesample',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('file_id', sa.Uuid(), nullable=False),
        sa.Column(
            'sample_name',
            sqlmodel.sql.sqltypes.AutoString(length=255),
            nullable=False
        ),
        sa.Column(
            'role',
            sqlmodel.sql.sqltypes.AutoString(length=50),
            nullable=True
        ),
        sa.ForeignKeyConstraint(['file_id'], ['file.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint(
            'file_id', 'sample_name',
            name='uq_filesample_file_sample'
        )
    )

    # ========================================================================
    # Step 2: Add new columns to file table
    # ========================================================================

    op.add_column(
        'file',
        sa.Column(
            'uri',
            sqlmodel.sql.sqltypes.AutoString(length=1024),
            nullable=True
        )
    )
    op.add_column(
        'file',
        sa.Column('size', sa.BigInteger(), nullable=True)
    )
    op.add_column(
        'file',
        sa.Column('created_on', sa.DateTime(), nullable=True)
    )
    op.add_column(
        'file',
        sa.Column(
            'source',
            sqlmodel.sql.sqltypes.AutoString(length=1024),
            nullable=True
        )
    )

    # ========================================================================
    # Step 3: Migrate data from old columns to new columns
    # ========================================================================

    # Copy file_path → uri, file_size → size, upload_date → created_on
    op.execute("""
        UPDATE file SET
            uri = file_path,
            size = file_size,
            created_on = upload_date
    """)

    # Migrate entity associations to fileentity table
    # (preserving entity_type and entity_id from file table)
    op.execute("""
        INSERT INTO fileentity (id, file_id, entity_type, entity_id, role)
        SELECT
            gen_random_uuid(),
            id,
            UPPER(entity_type::text),
            entity_id,
            NULL
        FROM file
    """)

    # Migrate checksum to filehash table (as sha256)
    op.execute("""
        INSERT INTO filehash (id, file_id, algorithm, value)
        SELECT
            gen_random_uuid(),
            id,
            'sha256',
            checksum
        FROM file
        WHERE checksum IS NOT NULL
    """)

    # Migrate description to filetag table
    op.execute("""
        INSERT INTO filetag (id, file_id, key, value)
        SELECT
            gen_random_uuid(),
            id,
            'description',
            description
        FROM file
        WHERE description IS NOT NULL AND description != ''
    """)

    # Migrate is_public to filetag table
    op.execute("""
        INSERT INTO filetag (id, file_id, key, value)
        SELECT
            gen_random_uuid(),
            id,
            'public',
            'true'
        FROM file
        WHERE is_public = true
    """)

    # Migrate is_archived to filetag table
    op.execute("""
        INSERT INTO filetag (id, file_id, key, value)
        SELECT
            gen_random_uuid(),
            id,
            'archived',
            'true'
        FROM file
        WHERE is_archived = true
    """)

    # ========================================================================
    # Step 4: Make uri NOT NULL and add unique constraint
    # ========================================================================

    op.alter_column('file', 'uri', nullable=False)
    op.alter_column('file', 'created_on', nullable=False)
    op.create_unique_constraint(
        'uq_file_uri_created_on', 'file', ['uri', 'created_on']
    )

    # ========================================================================
    # Step 5: Convert storage_backend from enum to varchar
    # ========================================================================

    op.add_column(
        'file',
        sa.Column(
            'storage_backend_new',
            sqlmodel.sql.sqltypes.AutoString(length=20),
            nullable=True
        )
    )
    op.execute(
        "UPDATE file SET storage_backend_new = UPPER(storage_backend::text)"
    )
    op.drop_column('file', 'storage_backend')
    op.alter_column(
        'file', 'storage_backend_new',
        new_column_name='storage_backend'
    )

    # ========================================================================
    # Step 6: Drop old columns from file table
    # ========================================================================

    op.drop_constraint('file_file_id_key', 'file', type_='unique')
    op.drop_column('file', 'file_id')
    op.drop_column('file', 'filename')
    op.drop_column('file', 'file_path')
    op.drop_column('file', 'file_size')
    op.drop_column('file', 'mime_type')
    op.drop_column('file', 'checksum')
    op.drop_column('file', 'description')
    op.drop_column('file', 'upload_date')
    op.drop_column('file', 'entity_type')
    op.drop_column('file', 'entity_id')
    op.drop_column('file', 'is_public')
    op.drop_column('file', 'is_archived')
    op.drop_column('file', 'relative_path')

    # Drop old enums
    op.execute("DROP TYPE IF EXISTS entitytype")
    op.execute("DROP TYPE IF EXISTS storagebackend")

    # ========================================================================
    # Step 7: Create QCRecord Tables
    # ========================================================================

    # qcrecord - main QC record table
    op.create_table(
        'qcrecord',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('created_on', sa.DateTime(), nullable=False),
        sa.Column(
            'created_by',
            sqlmodel.sql.sqltypes.AutoString(length=100),
            nullable=False
        ),
        sa.Column(
            'project_id',
            sqlmodel.sql.sqltypes.AutoString(length=50),
            nullable=False
        ),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_qcrecord_project_id', 'qcrecord', ['project_id'])

    # qcrecordmetadata - pipeline-level metadata
    op.create_table(
        'qcrecordmetadata',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('qcrecord_id', sa.Uuid(), nullable=False),
        sa.Column(
            'key',
            sqlmodel.sql.sqltypes.AutoString(length=255),
            nullable=False
        ),
        sa.Column('value', sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(
            ['qcrecord_id'], ['qcrecord.id'],
            ondelete='CASCADE'
        ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint(
            'qcrecord_id', 'key',
            name='uq_qcrecordmetadata_record_key'
        )
    )

    # qcmetric - named metric groups
    # NOTE: No unique constraint on (qcrecord_id, name) - multiple metrics with
    # the same name are allowed, differentiated by their sample associations.
    # For example, each sample gets its own QCMetric(name="sample_qc") row.
    op.create_table(
        'qcmetric',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('qcrecord_id', sa.Uuid(), nullable=False),
        sa.Column(
            'name',
            sqlmodel.sql.sqltypes.AutoString(length=255),
            nullable=False
        ),
        sa.ForeignKeyConstraint(
            ['qcrecord_id'], ['qcrecord.id'],
            ondelete='CASCADE'
        ),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_qcmetric_qcrecord_id', 'qcmetric', ['qcrecord_id'])
    op.create_index('ix_qcmetric_name', 'qcmetric', ['name'])

    # qcmetricvalue - metric values with dual storage for string/numeric queries
    op.create_table(
        'qcmetricvalue',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('qc_metric_id', sa.Uuid(), nullable=False),
        sa.Column(
            'key',
            sqlmodel.sql.sqltypes.AutoString(length=255),
            nullable=False
        ),
        sa.Column('value_string', sa.Text(), nullable=False),
        sa.Column('value_numeric', sa.Float(), nullable=True),
        sa.Column(
            'value_type',
            sqlmodel.sql.sqltypes.AutoString(length=10),
            nullable=False,
            server_default='str'
        ),
        sa.ForeignKeyConstraint(
            ['qc_metric_id'], ['qcmetric.id'],
            ondelete='CASCADE'
        ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint(
            'qc_metric_id', 'key',
            name='uq_qcmetricvalue_metric_key'
        )
    )
    op.create_index(
        'ix_qcmetricvalue_key_numeric', 'qcmetricvalue',
        ['key', 'value_numeric']
    )

    # qcmetricsample - sample associations for metrics
    op.create_table(
        'qcmetricsample',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('qc_metric_id', sa.Uuid(), nullable=False),
        sa.Column(
            'sample_name',
            sqlmodel.sql.sqltypes.AutoString(length=255),
            nullable=False
        ),
        sa.Column(
            'role',
            sqlmodel.sql.sqltypes.AutoString(length=50),
            nullable=True
        ),
        sa.ForeignKeyConstraint(
            ['qc_metric_id'], ['qcmetric.id'],
            ondelete='CASCADE'
        ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint(
            'qc_metric_id', 'sample_name',
            name='uq_qcmetricsample_metric_sample'
        )
    )
    # Index on sample_name for efficient queries like "find all metrics for sample X"
    op.create_index('ix_qcmetricsample_sample_name', 'qcmetricsample', ['sample_name'])


def downgrade() -> None:
    """Revert to original file schema and drop QCMetrics tables."""

    # Drop QCRecord tables
    op.drop_index('ix_qcmetricsample_sample_name', table_name='qcmetricsample')
    op.drop_table('qcmetricsample')
    op.drop_index('ix_qcmetricvalue_key_numeric', table_name='qcmetricvalue')
    op.drop_table('qcmetricvalue')
    op.drop_index('ix_qcmetric_name', table_name='qcmetric')
    op.drop_index('ix_qcmetric_qcrecord_id', table_name='qcmetric')
    op.drop_table('qcmetric')
    op.drop_table('qcrecordmetadata')
    op.drop_index('ix_qcrecord_project_id', table_name='qcrecord')
    op.drop_table('qcrecord')

    # Recreate enums
    op.execute("CREATE TYPE entitytype AS ENUM ('PROJECT', 'RUN')")
    op.execute("CREATE TYPE storagebackend AS ENUM ('LOCAL', 'S3', 'AZURE', 'GCS')")

    # Recreate old file columns
    op.add_column(
        'file',
        sa.Column(
            'file_id',
            sqlmodel.sql.sqltypes.AutoString(length=100),
            nullable=True
        )
    )
    op.add_column(
        'file',
        sa.Column(
            'filename',
            sqlmodel.sql.sqltypes.AutoString(length=255),
            nullable=True
        )
    )
    op.add_column(
        'file',
        sa.Column(
            'file_path',
            sqlmodel.sql.sqltypes.AutoString(length=1024),
            nullable=True
        )
    )
    op.add_column(
        'file',
        sa.Column('file_size', sa.Integer(), nullable=True)
    )
    op.add_column(
        'file',
        sa.Column(
            'mime_type',
            sqlmodel.sql.sqltypes.AutoString(length=100),
            nullable=True
        )
    )
    op.add_column(
        'file',
        sa.Column(
            'checksum',
            sqlmodel.sql.sqltypes.AutoString(length=64),
            nullable=True
        )
    )
    op.add_column(
        'file',
        sa.Column(
            'description',
            sqlmodel.sql.sqltypes.AutoString(length=1024),
            nullable=True
        )
    )
    op.add_column(
        'file',
        sa.Column('upload_date', sa.DateTime(), nullable=True)
    )
    op.add_column(
        'file',
        sa.Column(
            'entity_type_old',
            sa.Enum('PROJECT', 'RUN', name='entitytype'),
            nullable=True
        )
    )
    op.add_column(
        'file',
        sa.Column(
            'entity_id',
            sqlmodel.sql.sqltypes.AutoString(length=100),
            nullable=True
        )
    )
    op.add_column(
        'file',
        sa.Column(
            'is_public',
            sa.Boolean(),
            nullable=True,
            server_default='false'
        )
    )
    op.add_column(
        'file',
        sa.Column(
            'is_archived',
            sa.Boolean(),
            nullable=True,
            server_default='false'
        )
    )
    op.add_column(
        'file',
        sa.Column(
            'relative_path',
            sqlmodel.sql.sqltypes.AutoString(length=1024),
            nullable=True
        )
    )

    # Restore data from new to old columns
    op.execute("""
        UPDATE file SET
            file_path = uri,
            file_size = size,
            upload_date = created_on,
            filename = SPLIT_PART(uri, '/', -1)
    """)

    # Restore entity associations from fileentity
    op.execute("""
        UPDATE file f SET
            entity_type_old = fe.entity_type::entitytype,
            entity_id = fe.entity_id
        FROM fileentity fe
        WHERE fe.file_id = f.id
    """)

    # Restore checksum from filehash
    op.execute("""
        UPDATE file f SET checksum = fh.value
        FROM filehash fh
        WHERE fh.file_id = f.id AND fh.algorithm = 'sha256'
    """)

    # Restore description from filetag
    op.execute("""
        UPDATE file f SET description = ft.value
        FROM filetag ft
        WHERE ft.file_id = f.id AND ft.key = 'description'
    """)

    # Restore is_public from filetag
    op.execute("""
        UPDATE file f SET is_public = true
        FROM filetag ft
        WHERE ft.file_id = f.id AND ft.key = 'public' AND ft.value = 'true'
    """)

    # Restore is_archived from filetag
    op.execute("""
        UPDATE file f SET is_archived = true
        FROM filetag ft
        WHERE ft.file_id = f.id AND ft.key = 'archived' AND ft.value = 'true'
    """)

    # Generate file_id for each record
    op.execute("""
        UPDATE file SET file_id = SUBSTR(MD5(RANDOM()::TEXT), 1, 12)
    """)

    # Handle storage_backend conversion back to enum
    op.add_column(
        'file',
        sa.Column(
            'storage_backend_old',
            sa.Enum('LOCAL', 'S3', 'AZURE', 'GCS', name='storagebackend'),
            nullable=True
        )
    )
    op.execute(
        "UPDATE file SET storage_backend_old = storage_backend::storagebackend"
    )
    op.drop_column('file', 'storage_backend')
    op.alter_column(
        'file', 'storage_backend_old',
        new_column_name='storage_backend'
    )

    # Rename entity_type column
    op.alter_column(
        'file', 'entity_type_old',
        new_column_name='entity_type'
    )

    # Make required columns NOT NULL
    op.alter_column('file', 'file_id', nullable=False)
    op.alter_column('file', 'filename', nullable=False)
    op.alter_column('file', 'original_filename', nullable=False)
    op.alter_column('file', 'file_path', nullable=False)
    op.alter_column('file', 'upload_date', nullable=False)
    op.alter_column('file', 'entity_type', nullable=False)
    op.alter_column('file', 'entity_id', nullable=False)
    op.alter_column('file', 'storage_backend', nullable=False)
    op.alter_column('file', 'is_public', nullable=False)
    op.alter_column('file', 'is_archived', nullable=False)

    # Drop new columns and constraints
    op.drop_constraint('uq_file_uri_created_on', 'file', type_='unique')
    op.drop_column('file', 'uri')
    op.drop_column('file', 'size')
    op.drop_column('file', 'created_on')
    op.drop_column('file', 'source')

    # Recreate unique constraint on file_id
    op.create_unique_constraint('file_file_id_key', 'file', ['file_id'])

    # Drop File supporting tables
    op.drop_table('filesample')
    op.drop_table('filetag')
    op.drop_table('filehash')
    op.drop_index('ix_fileentity_entity', table_name='fileentity')
    op.drop_table('fileentity')
