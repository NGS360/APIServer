"""add run_id to sequencingrun

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
    # Add nullable run_id column
    op.add_column(
        'sequencingrun',
        sa.Column(
            'run_id',
            sqlmodel.sql.sqltypes.AutoString(length=100),
            nullable=True,
        ),
    )
    # Add unique index: MySQL allows multiple NULLs in a unique index,
    # so legacy rows without run_id are fine.
    op.create_index(
        'ix_sequencingrun_run_id',
        'sequencingrun',
        ['run_id'],
        unique=True,
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_sequencingrun_run_id', 'sequencingrun')
    op.drop_column('sequencingrun', 'run_id')
