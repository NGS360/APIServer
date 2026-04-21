"""add original_barcode to sequencingrun

Revision ID: 5d121c106e1a
Revises: 21274c7c470d
Create Date: 2026-04-17 15:54:54.117927

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel


# revision identifiers, used by Alembic.
revision: str = '5d121c106e1a'
down_revision: Union[str, Sequence[str], None] = '21274c7c470d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Add nullable original_barcode column
    op.add_column(
        'sequencingrun',
        sa.Column(
            'original_barcode',
            sqlmodel.sql.sqltypes.AutoString(length=100),
            nullable=True,
        ),
    )
    # Add partial unique index: uniqueness enforced for non-NULL values,
    # multiple NULLs allowed (legacy rows without original_barcode).
    op.create_index(
        'ix_sequencingrun_original_barcode',
        'sequencingrun',
        ['original_barcode'],
        unique=True,
        postgresql_where=sa.text('original_barcode IS NOT NULL'),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_sequencingrun_original_barcode', 'sequencingrun')
    op.drop_column('sequencingrun', 'original_barcode')
