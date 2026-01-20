"""seed additional system setting

Revision ID: 119ffa4fc867
Revises: d89d27d47634
Create Date: 2026-01-16 19:35:53.855844

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel
from sqlalchemy import table, column


# revision identifiers, used by Alembic.
revision: str = '119ffa4fc867'
down_revision: Union[str, Sequence[str], None] = 'd89d27d47634'
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


def downgrade() -> None:
    """Downgrade schema."""
    # Delete the seeded setting
    op.execute(
        "DELETE FROM setting WHERE `key` = 'PROJECT_WORKFLOW_CONFIGS_BUCKET_URI'"
    )
