"""Widen oauth_providers token columns to TEXT

Corporate SSO issues stateless JWT access tokens that exceed the previous
VARCHAR limit, causing MySQL error 1406 ("Data too long for column
'access_token'") on the OAuth callback. Widen access_token and refresh_token
to TEXT so tokens of any realistic size can be stored.

Revision ID: c4f8a1b2d3e5
Revises: a16a32f14864
Create Date: 2026-07-06 15:45:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c4f8a1b2d3e5'
down_revision: Union[str, Sequence[str], None] = 'a16a32f14864'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.alter_column(
        'oauth_providers', 'access_token',
        existing_type=sa.String(length=1000),
        type_=sa.Text(),
        existing_nullable=True,
    )
    op.alter_column(
        'oauth_providers', 'refresh_token',
        existing_type=sa.String(length=1000),
        type_=sa.Text(),
        existing_nullable=True,
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.alter_column(
        'oauth_providers', 'refresh_token',
        existing_type=sa.Text(),
        type_=sa.String(length=1000),
        existing_nullable=True,
    )
    op.alter_column(
        'oauth_providers', 'access_token',
        existing_type=sa.Text(),
        type_=sa.String(length=1000),
        existing_nullable=True,
    )
