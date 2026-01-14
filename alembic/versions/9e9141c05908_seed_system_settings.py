"""seed_system_settings

Revision ID: 9e9141c05908
Revises: 07c0715af653
Create Date: 2026-01-13 14:57:04.093577

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
down_revision: Union[str, Sequence[str], None] = '07c0715af653'
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
            'key': 'DEMUX_WORKFLOW_CONFIGS_BUCKET_URI',
            'value': '',
            'name': 'Demux Workflow Configs Bucket URI',
            'description': 'S3 bucket URI for storing demux workflow configuration files',
            'tags': [
                {'key': 'category', 'value': 'run settings'},
                {'key': 'type', 'value': 'aws-s3'}
            ]
        },
        {
            'key': 'MANIFEST_VALIDATION_LAMBDA',
            'value': '',
            'name': 'Manifest Validation Lambda',
            'description': 'ARN for the AWS Lambda function used to validate manifest files',
            'tags': [
                {'key': 'category', 'value': 'vendor settings'}
            ]
        }
    ])


def downgrade() -> None:
    """Downgrade schema."""
    # Delete the seeded settings
    op.execute(
        "DELETE FROM setting WHERE `key` IN ('DATA_BUCKET_URI', 'RESULTS_BUCKET_URI', 'DEMUX_WORKFLOW_CONFIGS_BUCKET_URI', 'MANIFEST_VALIDATION_LAMBDA')"
    )
