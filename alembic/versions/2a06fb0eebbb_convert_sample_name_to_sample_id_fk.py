"""convert_sample_name_to_sample_id_fk

Revision ID: 2a06fb0eebbb
Revises: f1a2b3c4d5e6
Create Date: 2026-02-23 10:17:13.197494

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql

# revision identifiers, used by Alembic.
revision: str = '2a06fb0eebbb'
down_revision: Union[str, Sequence[str], None] = 'f1a2b3c4d5e6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Convert filesample/qcmetricsample sample_name to sample_id FK."""

    # --- filesample ---
    # 1. Drop existing FK (file_id) that depends on the unique index
    op.drop_constraint(
        'filesample_ibfk_1', 'filesample', type_='foreignkey',
    )
    # 2. Drop old unique constraint (file_id, sample_name)
    op.drop_constraint(
        'uq_filesample_file_sample', 'filesample', type_='unique',
    )
    # 3. Drop old column
    op.drop_column('filesample', 'sample_name')
    # 4. Add new UUID column
    op.add_column(
        'filesample',
        sa.Column('sample_id', sa.Uuid(), nullable=False),
    )
    # 5. Recreate unique constraint with new column
    op.create_unique_constraint(
        'uq_filesample_file_sample', 'filesample',
        ['file_id', 'sample_id'],
    )
    # 6. Recreate file_id FK
    op.create_foreign_key(
        'fk_filesample_file_id', 'filesample', 'file',
        ['file_id'], ['id'], ondelete='CASCADE',
    )
    # 7. Add sample_id FK
    op.create_foreign_key(
        'fk_filesample_sample_id', 'filesample', 'sample',
        ['sample_id'], ['id'], ondelete='CASCADE',
    )

    # --- qcmetricsample ---
    # 1. Drop existing FK (qc_metric_id) that depends on unique index
    op.drop_constraint(
        'qcmetricsample_ibfk_1', 'qcmetricsample',
        type_='foreignkey',
    )
    # 2. Drop old unique constraint (qc_metric_id, sample_name)
    op.drop_constraint(
        'uq_qcmetricsample_metric_sample', 'qcmetricsample',
        type_='unique',
    )
    # 3. Drop old index on sample_name
    op.drop_index(
        'ix_qcmetricsample_sample_name',
        table_name='qcmetricsample',
    )
    # 4. Drop old column
    op.drop_column('qcmetricsample', 'sample_name')
    # 5. Add new UUID column
    op.add_column(
        'qcmetricsample',
        sa.Column('sample_id', sa.Uuid(), nullable=False),
    )
    # 6. Recreate unique constraint with new column
    op.create_unique_constraint(
        'uq_qcmetricsample_metric_sample', 'qcmetricsample',
        ['qc_metric_id', 'sample_id'],
    )
    # 7. Add index on sample_id
    op.create_index(
        'ix_qcmetricsample_sample_id', 'qcmetricsample',
        ['sample_id'], unique=False,
    )
    # 8. Recreate qc_metric_id FK
    op.create_foreign_key(
        'fk_qcmetricsample_metric_id', 'qcmetricsample', 'qcmetric',
        ['qc_metric_id'], ['id'], ondelete='CASCADE',
    )
    # 9. Add sample_id FK
    op.create_foreign_key(
        'fk_qcmetricsample_sample_id', 'qcmetricsample', 'sample',
        ['sample_id'], ['id'], ondelete='CASCADE',
    )


def downgrade() -> None:
    """Revert sample_id FK back to sample_name VARCHAR."""

    # --- qcmetricsample: revert ---
    op.drop_constraint(
        'fk_qcmetricsample_sample_id', 'qcmetricsample',
        type_='foreignkey',
    )
    op.drop_constraint(
        'fk_qcmetricsample_metric_id', 'qcmetricsample',
        type_='foreignkey',
    )
    op.drop_index(
        'ix_qcmetricsample_sample_id',
        table_name='qcmetricsample',
    )
    op.drop_constraint(
        'uq_qcmetricsample_metric_sample', 'qcmetricsample',
        type_='unique',
    )
    op.drop_column('qcmetricsample', 'sample_id')
    op.add_column(
        'qcmetricsample',
        sa.Column(
            'sample_name', mysql.VARCHAR(length=255),
            nullable=False,
        ),
    )
    op.create_unique_constraint(
        'uq_qcmetricsample_metric_sample', 'qcmetricsample',
        ['qc_metric_id', 'sample_name'],
    )
    op.create_index(
        'ix_qcmetricsample_sample_name', 'qcmetricsample',
        ['sample_name'], unique=False,
    )
    op.create_foreign_key(
        'qcmetricsample_ibfk_1', 'qcmetricsample', 'qcmetric',
        ['qc_metric_id'], ['id'], ondelete='CASCADE',
    )

    # --- filesample: revert ---
    op.drop_constraint(
        'fk_filesample_sample_id', 'filesample',
        type_='foreignkey',
    )
    op.drop_constraint(
        'fk_filesample_file_id', 'filesample',
        type_='foreignkey',
    )
    op.drop_constraint(
        'uq_filesample_file_sample', 'filesample', type_='unique',
    )
    op.drop_column('filesample', 'sample_id')
    op.add_column(
        'filesample',
        sa.Column(
            'sample_name', mysql.VARCHAR(length=255),
            nullable=False,
        ),
    )
    op.create_unique_constraint(
        'uq_filesample_file_sample', 'filesample',
        ['file_id', 'sample_name'],
    )
    op.create_foreign_key(
        'filesample_ibfk_1', 'filesample', 'file',
        ['file_id'], ['id'], ondelete='CASCADE',
    )
