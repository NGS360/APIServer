"""add additional system settings

Revision ID: c9fbcc25cd06
Revises: b6847b89d202
Create Date: 2026-02-04 15:55:55.517103

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel
from sqlalchemy import table, column

# revision identifiers, used by Alembic.
revision: str = 'c9fbcc25cd06'
down_revision: Union[str, Sequence[str], None] = 'b6847b89d202'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Define the settings table for data insertion
    setting_table = table('setting',
        column('key', sa.String),
        column('value', sa.String),
        column('name', sa.String),
        column('description', sa.String),
        column('tags', sa.JSON),
    )
    # Insert system setting
    op.bulk_insert(setting_table, [
        {
            'key': 'PROJECT_WORKFLOW_CONFIGS_BUCKET_URI',
            'value': '',
            'name': 'Project Workflow Configs Bucket URI',
            'description': 'S3 bucket URI for storing project workflow configuration files',
            'tags': [
                {'key': 'category', 'value': 'project settings'}
            ]
        }
    ])
    # ### end Alembic commands ###


def downgrade() -> None:
    """Downgrade schema."""
    op.execute(
        "DELETE FROM setting WHERE `key` = 'PROJECT_WORKFLOW_CONFIGS_BUCKET_URI'"
    )
    # ### end Alembic commands ###
