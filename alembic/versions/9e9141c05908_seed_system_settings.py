"""seed_system_settings

Revision ID: 9e9141c05908
Revises: 6c6c80d9aaeb
Create Date: 2026-01-08 22:31:47.768783

"""
from typing import Sequence, Union
from datetime import datetime

from alembic import op
import sqlalchemy as sa
import sqlmodel
from sqlalchemy import table, column
from sqlalchemy.sql import insert


# revision identifiers, used by Alembic.
revision: str = '9e9141c05908'
down_revision: Union[str, Sequence[str], None] = '6c6c80d9aaeb'
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
    
    # Insert system settings
    op.bulk_insert(setting_table, [
        {
            'key': 'DATA_BUCKET_URI',
            'value': '',
            'name': 'Data Bucket URI',
            'description': 'S3 bucket URI for storing NGS data files',
            'tags': [
                {'key': 'category', 'value': 'project settings'}
            ]
        },
        {
            'key': 'RESULTS_BUCKET_URI',
            'value': '',
            'name': 'Results Bucket URI',
            'description': 'S3 bucket URI for storing analysis results',
            'tags': [
                {'key': 'category', 'value': 'project settings'}
            ]
        },
        {
            'key': 'TOOL_CONFIGS_BUCKET_URI',
            'value': '',
            'name': 'Tool Configs Bucket URI',
            'description': 'S3 bucket URI for storing tool configuration files',
            'tags': [
                {'key': 'category', 'value': 'run settings'},
                {'key': 'type', 'value': 'aws-s3'}
            ]
        },
        {
            'key': 'AWS_ACCESS_KEY_ID',
            'value': '',
            'name': 'AWS Access Key ID',
            'description': 'AWS access key ID for authenticating API requests',
            'tags': [
                {'key': 'category', 'value': 'aws credentials'}
            ]
        },
        {
            'key': 'AWS_SECRET_ACCESS_KEY',
            'value': '',
            'name': 'AWS Secret Access Key',
            'description': 'AWS secret access key for authenticating API requests',
            'tags': [
                {'key': 'category', 'value': 'aws credentials'}
            ]
        },
        {
            'key': 'AWS_REGION',
            'value': '',
            'name': 'AWS Region',
            'description': 'AWS region for resource deployment and API calls',
            'tags': [
                {'key': 'category', 'value': 'aws credentials'}
            ]
        }
    ])


def downgrade() -> None:
    """Downgrade schema."""
    # Delete the seeded settings
    op.execute(
        "DELETE FROM setting WHERE key IN ('DATA_BUCKET_URI', 'RESULTS_BUCKET_URI', 'TOOL_CONFIGS_BUCKET_URI', 'AWS_ACCESS_KEY_ID', 'AWS_SECRET_ACCESS_KEY', 'AWS_REGION')"
    )
