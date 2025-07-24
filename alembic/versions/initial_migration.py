"""Initial migration

Revision ID: initial_migration
Revises: 
Create Date: 2025-07-24

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel

# revision identifiers, used by Alembic.
revision: str = 'initial_migration'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Create project_attribute table
    op.create_table(
        'projectattribute',
        sa.Column('id', sqlmodel.sql.sqltypes.GUID(), nullable=False),
        sa.Column('project_id', sqlmodel.sql.sqltypes.GUID(), nullable=False),
        sa.Column('key', sa.String(), nullable=False),
        sa.Column('value', sa.String(), nullable=False),
        sa.ForeignKeyConstraint(['project_id'], ['project.id']),
        sa.PrimaryKeyConstraint('id', 'project_id'),
        sa.UniqueConstraint('project_id', 'key')
    )

    # Create project table
    op.create_table(
        'project',
        sa.Column('id', sqlmodel.sql.sqltypes.GUID(), nullable=False),
        sa.Column('project_id', sa.String(), nullable=False),
        sa.Column('name', sa.String(length=2048), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('project_id')
    )


def downgrade() -> None:
    # Drop tables in reverse order of creation
    op.drop_table('projectattribute')
    op.drop_table('project')