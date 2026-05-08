"""rename workflowregistration to workflowdeployment

Revision ID: 8a5d5a8bb9f6
Revises: 908e88cdaf0e
Create Date: 2026-03-23 16:48:03.722268

"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '8a5d5a8bb9f6'
down_revision: Union[str, Sequence[str], None] = '908e88cdaf0e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Rename workflowregistration table to workflowdeployment."""
    # Drop existing FK constraints (their names reference 'registration')
    op.drop_constraint(
        'workflowregistration_ibfk_1',
        'workflowregistration',
        type_='foreignkey',
    )
    op.drop_constraint(
        'fk_wfreg_workflowversion',
        'workflowregistration',
        type_='foreignkey',
    )

    # Rename the table (preserves data, PK, unique constraints, and indexes)
    op.rename_table('workflowregistration', 'workflowdeployment')

    # Re-create FK constraints with updated names
    op.create_foreign_key(
        'workflowdeployment_ibfk_1',
        'workflowdeployment', 'platform',
        ['engine'], ['name'],
    )
    op.create_foreign_key(
        'fk_wfdeploy_workflowversion',
        'workflowdeployment', 'workflowversion',
        ['workflow_version_id'], ['id'],
    )


def downgrade() -> None:
    """Rename workflowdeployment table back to workflowregistration."""
    # Drop the deployment-era FK constraints
    op.drop_constraint(
        'workflowdeployment_ibfk_1',
        'workflowdeployment',
        type_='foreignkey',
    )
    op.drop_constraint(
        'fk_wfdeploy_workflowversion',
        'workflowdeployment',
        type_='foreignkey',
    )

    # Rename the table back
    op.rename_table('workflowdeployment', 'workflowregistration')

    # Re-create original FK constraints
    op.create_foreign_key(
        'workflowregistration_ibfk_1',
        'workflowregistration', 'platform',
        ['engine'], ['name'],
    )
    op.create_foreign_key(
        'fk_wfreg_workflowversion',
        'workflowregistration', 'workflowversion',
        ['workflow_version_id'], ['id'],
    )
