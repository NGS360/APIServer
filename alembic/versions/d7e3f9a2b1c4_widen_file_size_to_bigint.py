"""Widen file.size column to BIGINT

NGS FASTQ files routinely exceed 2 GB, which overflows a signed 32-bit INT
(max 2,147,483,647 bytes ≈ 2.1 GB), causing MySQL error 1264 ("Out of range
value for column 'size'") on file creation. Widen file.size to BIGINT so file
sizes of any realistic magnitude can be stored.

Revision ID: d7e3f9a2b1c4
Revises: c4f8a1b2d3e5
Create Date: 2026-07-10 19:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd7e3f9a2b1c4'
down_revision: Union[str, Sequence[str], None] = 'c4f8a1b2d3e5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.alter_column(
        'file', 'size',
        existing_type=sa.Integer(),
        type_=sa.BigInteger(),
        existing_nullable=True,
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.alter_column(
        'file', 'size',
        existing_type=sa.BigInteger(),
        type_=sa.Integer(),
        existing_nullable=True,
    )
