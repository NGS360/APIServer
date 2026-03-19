"""Change run_number from Integer to String for ONT support

Revision ID: a1b2c3d4e5f6
Revises: 0706aaf19b43
Create Date: 2026-03-19 00:38:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel


# revision identifiers, used by Alembic.
revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, Sequence[str]] = '0706aaf19b43'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Change run_number column from Integer to String.

    ONT run numbers can be arbitrary strings (e.g. 'abc123'),
    not just zero-padded integers like Illumina runs.
    """
    # Convert existing integer values to strings, then alter the column type
    op.alter_column(
        'sequencingrun',
        'run_number',
        existing_type=sa.Integer(),
        type_=sqlmodel.sql.sqltypes.AutoString(length=50),
        existing_nullable=False,
        postgresql_using='run_number::text',
    )


def downgrade() -> None:
    """Revert run_number column from String back to Integer.

    WARNING: This will fail if any non-numeric run_number values exist.
    """
    op.alter_column(
        'sequencingrun',
        'run_number',
        existing_type=sqlmodel.sql.sqltypes.AutoString(length=50),
        type_=sa.Integer(),
        existing_nullable=False,
        postgresql_using='run_number::integer',
    )
