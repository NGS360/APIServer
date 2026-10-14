"""Collapse the role model to three tiers

Revision ID: a71c4e08b2f6
Revises: f3a7c01d9e45
Create Date: 2026-10-13

NWP-2213, step 3. Retires five global roles and widens the default role to
everything not reserved.

Retired: lab_manager, demux_operator, manifest_operator, workflow_publisher,
platform_admin. Their holders are covered by the widened `member` with one
exception -- workflow_publisher carried workflow:create/update/deploy, which
are reserved to workflow_admin, so its holders are granted workflow_admin here
rather than silently losing access.

**Why this migration writes `member`'s permissions itself**, when
sync_rbac_catalog would do it at the next startup: the two steps are not
simultaneous. `alembic upgrade head` runs before the application restarts, so
between them a holder of a retired role has lost their grant while `member` has
not yet gained the permissions that replace it. For manifest_operator's
eighteen holders that window is a real outage, however short. Doing both in one
transaction removes it, and sync_rbac_catalog then reconciles to the same state,
so the duplication is a sequencing fix rather than a second source of truth.

The permission list is spelled out rather than imported from api.rbac.roles.
A migration has to mean the same thing when replayed against a future version
of the code, and importing a module that is edited every week does not.

Order-independent: if the application happens to restart first,
sync_rbac_catalog only iterates the roles that still exist in code, so the
retired rows survive untouched for this migration to remove.
"""
from alembic import op
import sqlalchemy as sa


revision = 'a71c4e08b2f6'
down_revision = 'f3a7c01d9e45'
branch_labels = None
depends_on = None


RETIRED = (
    'lab_manager',
    'demux_operator',
    'manifest_operator',
    'workflow_publisher',
    'platform_admin',
)

MEMBER_PERMISSIONS = (
    'action:read', 'action:validate', 'chat:use', 'file:browse',
    'file:create', 'file:delete', 'file:download', 'file:read',
    'file:update', 'job:read', 'job:read_all', 'job:submit',
    'manifest:read', 'manifest:upload', 'manifest:validate', 'pipeline:create',
    'pipeline:read', 'pipeline:update', 'platform:create', 'platform:read',
    'project:create', 'project:ingest', 'project:read', 'project:submit_action',
    'project:update', 'qcrecord:create', 'qcrecord:delete', 'qcrecord:read',
    'role:read', 'run:associate', 'run:create', 'run:demux',
    'run:read', 'run:update', 'sample:create', 'sample:delete',
    'sample:read', 'sample:update', 'search:query', 'setting:read',
    'user:read', 'vendor:read', 'workflow:read',
)


# Every surrogate key in these tables is char(32) -- an undashed uuid hex --
# and NOT NULL with no database default, because the application mints them in
# Python. A raw INSERT therefore has to supply one, and MySQL's UUID() returns
# the dashed 36-character form, so it needs stripping. Three inserts in this
# file got that wrong before the column types were checked.
def _role_id(conn, name):
    return conn.execute(
        sa.text("SELECT id FROM role WHERE name = :n"), {"n": name}
    ).scalar()


def upgrade() -> None:
    conn = op.get_bind()

    # 1. Widen `member` first, so nobody is between roles.
    member_id = _role_id(conn, 'member')
    if member_id is not None:
        existing = {
            r[0] for r in conn.execute(
                sa.text("SELECT permission FROM role_permission "
                        "WHERE role_id = :r"), {"r": member_id})
        }
        for permission in MEMBER_PERMISSIONS:
            if permission not in existing:
                conn.execute(
                    sa.text("INSERT INTO role_permission (id, role_id, permission) "
                            "VALUES (REPLACE(UUID(), '-', ''), :r, :p)"),
                    {"r": member_id, "p": permission},
                )

    # 2. workflow_publisher's holders keep what it granted, via workflow_admin.
    #    workflow_admin is a builtin role that already exists in every tier with
    #    zero holders, so no row has to be created for it here.
    publisher_id = _role_id(conn, 'workflow_publisher')
    admin_id = _role_id(conn, 'workflow_admin')
    if publisher_id is not None and admin_id is not None:
        conn.execute(
            sa.text(
                "INSERT INTO user_role "
                "       (id, user_id, role_id, source, granted_at) "
                "SELECT REPLACE(UUID(), '-', ''), ur.user_id, :new_role, "
                "       'MIGRATION', NOW() "
                "FROM user_role ur "
                "WHERE ur.role_id = :old_role "
                "  AND NOT EXISTS (SELECT 1 FROM user_role x "
                "                  WHERE x.user_id = ur.user_id "
                "                    AND x.role_id = :new_role)"
            ),
            {"new_role": admin_id, "old_role": publisher_id},
        )

    # 3. Remove the retired roles, grants first for the foreign keys.
    for name in RETIRED:
        role_id = _role_id(conn, name)
        if role_id is None:
            continue
        conn.execute(sa.text("DELETE FROM user_role WHERE role_id = :r"),
                     {"r": role_id})
        conn.execute(sa.text("DELETE FROM project_member WHERE role_id = :r"),
                     {"r": role_id})
        conn.execute(sa.text("DELETE FROM role_permission WHERE role_id = :r"),
                     {"r": role_id})
        conn.execute(sa.text("DELETE FROM role WHERE id = :r"), {"r": role_id})


def downgrade() -> None:
    """
    Recreates the retired roles as empty shells and narrows `member` back.

    Deliberately does **not** restore their grants: which users held
    manifest_operator is not recoverable from anything this migration left
    behind, and inventing a grant list would be worse than leaving it empty.
    A real rollback means restoring from a backup; this exists so the chain is
    reversible for `alembic downgrade base` in CI, not as an operational undo.
    """
    conn = op.get_bind()

    member_id = _role_id(conn, 'member')
    if member_id is not None:
        kept = (
            'action:read', 'chat:use', 'file:read', 'job:read', 'job:submit',
            'pipeline:read', 'platform:read', 'project:create', 'project:read',
            'qcrecord:read', 'run:demux', 'run:read', 'run:update',
            'sample:read', 'search:query', 'setting:read', 'user:read',
            'vendor:read', 'workflow:read', 'project:submit_action',
        )
        conn.execute(
            sa.text("DELETE FROM role_permission WHERE role_id = :r "
                    "AND permission NOT IN :kept").bindparams(
                        sa.bindparam("kept", expanding=True)),
            {"r": member_id, "kept": list(kept)},
        )

    for name in RETIRED:
        if _role_id(conn, name) is None:
            conn.execute(
                sa.text("INSERT INTO role (id, name, display_name, description, "
                        "scope, is_builtin, created_at, updated_at) "
                        "VALUES (REPLACE(UUID(), '-', ''), :n, :n, "
                        "'Recreated by downgrade; grants not restored', "
                        "'GLOBAL', 1, NOW(), NOW())"),
                {"n": name},
            )
