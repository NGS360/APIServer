"""Add QCMetrics and FileRecord tables

Revision ID: f1a2b3c4d5e6
Revises: e158df5a8df1
Create Date: 2026-01-29 16:45:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel


# revision identifiers, used by Alembic.
revision: str = 'f1a2b3c4d5e6'
down_revision: Union[str, Sequence[str], None] = 'e158df5a8df1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create QCMetrics and FileRecord tables."""

    # ========================================================================
    # FileRecord Tables (reusable across QCRecord, Sample, etc.)
    # ========================================================================

    # filerecord - main file metadata table
    op.create_table(
        'filerecord',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('entity_type', sqlmodel.sql.sqltypes.AutoString(length=50), nullable=False),
        sa.Column('entity_id', sa.Uuid(), nullable=False),
        sa.Column('uri', sqlmodel.sql.sqltypes.AutoString(length=1024), nullable=False),
        sa.Column('size', sa.BigInteger(), nullable=True),
        sa.Column('created_on', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(
        'ix_filerecord_entity',
        'filerecord',
        ['entity_type', 'entity_id']
    )

    # filerecordhash - hash values for files
    op.create_table(
        'filerecordhash',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('file_record_id', sa.Uuid(), nullable=False),
        sa.Column('algorithm', sqlmodel.sql.sqltypes.AutoString(length=50), nullable=False),
        sa.Column('value', sqlmodel.sql.sqltypes.AutoString(length=128), nullable=False),
        sa.ForeignKeyConstraint(['file_record_id'], ['filerecord.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('file_record_id', 'algorithm', name='uq_filerecordhash_file_algorithm')
    )

    # filerecordtag - key-value tags for files
    op.create_table(
        'filerecordtag',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('file_record_id', sa.Uuid(), nullable=False),
        sa.Column('key', sqlmodel.sql.sqltypes.AutoString(length=255), nullable=False),
        sa.Column('value', sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(['file_record_id'], ['filerecord.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('file_record_id', 'key', name='uq_filerecordtag_file_key')
    )

    # filerecordsample - sample associations for files
    op.create_table(
        'filerecordsample',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('file_record_id', sa.Uuid(), nullable=False),
        sa.Column('sample_name', sqlmodel.sql.sqltypes.AutoString(length=255), nullable=False),
        sa.Column('role', sqlmodel.sql.sqltypes.AutoString(length=50), nullable=True),
        sa.ForeignKeyConstraint(['file_record_id'], ['filerecord.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('file_record_id', 'sample_name', name='uq_filerecordsample_file_sample')
    )

    # ========================================================================
    # QCRecord Tables
    # ========================================================================

    # qcrecord - main QC record table
    op.create_table(
        'qcrecord',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('created_on', sa.DateTime(), nullable=False),
        sa.Column('created_by', sqlmodel.sql.sqltypes.AutoString(length=100), nullable=False),
        sa.Column('project_id', sqlmodel.sql.sqltypes.AutoString(length=50), nullable=False),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_qcrecord_project_id', 'qcrecord', ['project_id'])

    # qcrecordmetadata - pipeline-level metadata
    op.create_table(
        'qcrecordmetadata',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('qcrecord_id', sa.Uuid(), nullable=False),
        sa.Column('key', sqlmodel.sql.sqltypes.AutoString(length=255), nullable=False),
        sa.Column('value', sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(['qcrecord_id'], ['qcrecord.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('qcrecord_id', 'key', name='uq_qcrecordmetadata_record_key')
    )

    # qcmetric - named metric groups
    op.create_table(
        'qcmetric',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('qcrecord_id', sa.Uuid(), nullable=False),
        sa.Column('name', sqlmodel.sql.sqltypes.AutoString(length=255), nullable=False),
        sa.ForeignKeyConstraint(['qcrecord_id'], ['qcrecord.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('qcrecord_id', 'name', name='uq_qcmetric_record_name')
    )

    # qcmetricvalue - metric values with dual storage for string/numeric queries
    op.create_table(
        'qcmetricvalue',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('qc_metric_id', sa.Uuid(), nullable=False),
        sa.Column('key', sqlmodel.sql.sqltypes.AutoString(length=255), nullable=False),
        sa.Column('value_string', sa.Text(), nullable=False),
        sa.Column('value_numeric', sa.Float(), nullable=True),
        sa.Column(
            'value_type', sqlmodel.sql.sqltypes.AutoString(length=10),
            nullable=False, server_default='str'
        ),
        sa.ForeignKeyConstraint(['qc_metric_id'], ['qcmetric.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('qc_metric_id', 'key', name='uq_qcmetricvalue_metric_key')
    )
    # Index on key + value_numeric for efficient numeric range queries
    op.create_index(
        'ix_qcmetricvalue_key_numeric', 'qcmetricvalue',
        ['key', 'value_numeric']
    )

    # qcmetricsample - sample associations for metrics
    op.create_table(
        'qcmetricsample',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('qc_metric_id', sa.Uuid(), nullable=False),
        sa.Column('sample_name', sqlmodel.sql.sqltypes.AutoString(length=255), nullable=False),
        sa.Column('role', sqlmodel.sql.sqltypes.AutoString(length=50), nullable=True),
        sa.ForeignKeyConstraint(['qc_metric_id'], ['qcmetric.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('qc_metric_id', 'sample_name', name='uq_qcmetricsample_metric_sample')
    )


def downgrade() -> None:
    """Drop QCMetrics and FileRecord tables."""

    # Drop QCRecord tables (in reverse order of creation)
    op.drop_table('qcmetricsample')
    op.drop_index('ix_qcmetricvalue_key_numeric', table_name='qcmetricvalue')
    op.drop_table('qcmetricvalue')
    op.drop_table('qcmetric')
    op.drop_table('qcrecordmetadata')
    op.drop_index('ix_qcrecord_project_id', table_name='qcrecord')
    op.drop_table('qcrecord')

    # Drop FileRecord tables
    op.drop_table('filerecordsample')
    op.drop_table('filerecordtag')
    op.drop_table('filerecordhash')
    op.drop_index('ix_filerecord_entity', table_name='filerecord')
    op.drop_table('filerecord')
