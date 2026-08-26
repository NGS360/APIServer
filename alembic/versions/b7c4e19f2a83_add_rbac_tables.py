"""Add RBAC tables: role, role_permission, user_role, project_member

Additive only. Four new tables and nothing else -- no existing table is touched,
so the old application version runs against this schema unchanged. That matters
because migrations run pre-promotion on the leader with no blue/green, so old
code always meets the new schema on the remaining instances.

docs/RBAC.md sketched deferring the unique constraints to a later revision. That
advice is about adding constraints to tables the old code already writes to;
these tables are new and no deployed code touches them, so there is no
compatibility window and they are created fully formed.

Revision ID: b7c4e19f2a83
Revises: d7e3f9a2b1c4
Create Date: 2026-08-07

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel


# revision identifiers, used by Alembic.
revision: str = 'b7c4e19f2a83'
down_revision: Union[str, Sequence[str], None] = 'd7e3f9a2b1c4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'role',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('name', sqlmodel.sql.sqltypes.AutoString(length=64), nullable=False),
        sa.Column('display_name', sqlmodel.sql.sqltypes.AutoString(length=128), nullable=False),
        sa.Column('description', sqlmodel.sql.sqltypes.AutoString(length=512), nullable=True),
        sa.Column('scope', sa.Enum('GLOBAL', 'PROJECT', name='rolescope'), nullable=False),
        sa.Column('is_builtin', sa.Boolean(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_role_name'), 'role', ['name'], unique=True)
    op.create_index(op.f('ix_role_scope'), 'role', ['scope'], unique=False)

    op.create_table(
        'role_permission',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('role_id', sa.Uuid(), nullable=False),
        sa.Column('permission', sqlmodel.sql.sqltypes.AutoString(length=64), nullable=False),
        sa.ForeignKeyConstraint(['role_id'], ['role.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('role_id', 'permission', name='uq_role_permission'),
    )
    op.create_index(
        op.f('ix_role_permission_role_id'), 'role_permission', ['role_id'], unique=False
    )

    op.create_table(
        'user_role',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('user_id', sa.Uuid(), nullable=False),
        sa.Column('role_id', sa.Uuid(), nullable=False),
        sa.Column(
            'source',
            sa.Enum('MANUAL', 'BOOTSTRAP', 'MIGRATION', 'DIRECTORY', name='grantsource'),
            nullable=False,
        ),
        sa.Column('granted_by', sa.Uuid(), nullable=True),
        sa.Column('granted_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['granted_by'], ['users.id'], ),
        sa.ForeignKeyConstraint(['role_id'], ['role.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('user_id', 'role_id', name='uq_user_role'),
    )
    op.create_index(op.f('ix_user_role_role_id'), 'user_role', ['role_id'], unique=False)
    op.create_index(op.f('ix_user_role_user_id'), 'user_role', ['user_id'], unique=False)

    op.create_table(
        'project_member',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('project_id', sa.Uuid(), nullable=False),
        sa.Column('user_id', sa.Uuid(), nullable=False),
        sa.Column('role_id', sa.Uuid(), nullable=False),
        sa.Column(
            'source',
            sa.Enum('MANUAL', 'BOOTSTRAP', 'MIGRATION', 'DIRECTORY', name='grantsource'),
            nullable=False,
        ),
        sa.Column('granted_by', sa.Uuid(), nullable=True),
        sa.Column('granted_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['granted_by'], ['users.id'], ),
        sa.ForeignKeyConstraint(['project_id'], ['project.id'], ondelete='CASCADE'),
        # RESTRICT: deleting a role that is still granted should fail loudly
        # rather than silently revoking access.
        sa.ForeignKeyConstraint(['role_id'], ['role.id'], ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('project_id', 'user_id', name='uq_project_member'),
    )
    op.create_index(
        op.f('ix_project_member_project_id'), 'project_member', ['project_id'], unique=False
    )
    op.create_index(
        op.f('ix_project_member_user_id'), 'project_member', ['user_id'], unique=False
    )


def downgrade() -> None:
    """Downgrade schema.

    Dropped in reverse dependency order: the grant tables reference role, so they
    go first. Safe -- no other table references these, and dropping them removes
    only authorization data, which the seeding step recreates on next startup.
    Grants themselves are lost, which is why the operational rollback for RBAC is
    revoking the offending grant rather than a downgrade.

    Deliberately no drop_index() calls, though autogenerate would emit them.

    They are unnecessary: DROP TABLE removes the table's indexes with it. On MySQL
    they are also illegal. InnoDB requires an index on a foreign key's referencing
    column and uses that index to enforce the constraint, so dropping it while the
    FK exists fails with:

        (1553, "Cannot drop index 'ix_project_member_user_id':
                needed in a foreign key constraint")

    Every index here except ix_role_name and ix_role_scope sits on an FK column,
    so this applies to almost all of them. Note SQLite does not reproduce it -- it
    neither requires an index to enforce a foreign key nor refuses the drop -- so
    a SQLite round-trip passes and gives false confidence. Verified against MySQL.
    """
    op.drop_table('project_member')
    op.drop_table('user_role')
    op.drop_table('role_permission')
    op.drop_table('role')
