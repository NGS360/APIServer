"""Make run_registrar a custom role instead of a builtin one

Revision ID: c8e4a1f72b93
Revises: b4d17c3e9f52
Create Date: 2026-10-21

`run_registrar` was removed from ROLE_DEFINITIONS in api/rbac/roles.py. That
alone is not enough, and the gap is the whole reason this migration exists:
sync_rbac_catalog() never deletes a role it no longer defines, so without this
the row would survive in every tier still carrying `is_builtin = 1` -- a role
with no code definition behind it that update_role_permissions() and
delete_role() would both go on refusing. Stranded: uneditable through the API
and no longer re-derived from code either. Strictly worse than either state.

So this flips the flag, which is what actually hands the role to administrators.

Written to be idempotent and to not care what state the tier is in:

* **Row present** (every tier today -- prod carries it with `run:create` and one
  grant, to the sequencer upload service): flip `is_builtin` to 0, touch
  nothing else. The permission row and the grant are left exactly as they are,
  because converting a role must not disturb what it grants or who holds it.
* **Row absent** (a database created after this deploy, where the catalog sync
  will no longer make one): create it, with its `run:create` permission row, so
  tiers do not drift. This is a one-time data seed, not an ownership claim --
  nothing re-derives it afterwards.
* **Permission row missing but role present**: added, for the same reason.

`role.id` and `role_permission.id` are CHAR(32) NOT NULL with no server
default, holding undashed hex. They are generated here with `uuid4().hex`
rather than MySQL's `UUID()`, which returns the dashed 36-character form and
would be silently truncated into a corrupt key.
"""
from typing import Sequence, Union
from uuid import uuid4

import sqlalchemy as sa
from alembic import op

revision: str = 'c8e4a1f72b93'
down_revision: Union[str, Sequence[str], None] = 'b4d17c3e9f52'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

ROLE_NAME = "run_registrar"
PERMISSION = "run:create"
DISPLAY_NAME = "Run Registrar"
DESCRIPTION = (
    "May register sequencing runs. Grants nothing else. Custom role: owned by "
    "administrators through /rbac/roles, not re-derived from code on deploy."
)


def upgrade() -> None:
    conn = op.get_bind()

    role_id = conn.execute(
        sa.text("SELECT id FROM role WHERE name = :name"), {"name": ROLE_NAME}
    ).scalar()

    if role_id is None:
        role_id = uuid4().hex
        conn.execute(
            sa.text(
                "INSERT INTO role "
                "(id, name, display_name, description, scope, is_builtin, "
                " created_at, updated_at) "
                "VALUES (:id, :name, :display_name, :description, 'GLOBAL', 0, "
                " UTC_TIMESTAMP(), UTC_TIMESTAMP())"
            ),
            {
                "id": role_id,
                "name": ROLE_NAME,
                "display_name": DISPLAY_NAME,
                "description": DESCRIPTION,
            },
        )
    else:
        # The ordinary path. Only the flag moves -- not the description, which an
        # administrator may already have edited, and emphatically not the
        # permission rows or the grants.
        conn.execute(
            sa.text("UPDATE role SET is_builtin = 0, updated_at = UTC_TIMESTAMP() "
                    "WHERE id = :id AND is_builtin <> 0"),
            {"id": role_id},
        )

    has_permission = conn.execute(
        sa.text("SELECT 1 FROM role_permission "
                "WHERE role_id = :role_id AND permission = :permission"),
        {"role_id": role_id, "permission": PERMISSION},
    ).scalar()

    if not has_permission:
        conn.execute(
            sa.text("INSERT INTO role_permission (id, role_id, permission) "
                    "VALUES (:id, :role_id, :permission)"),
            {"id": uuid4().hex, "role_id": role_id, "permission": PERMISSION},
        )


def downgrade() -> None:
    """
    Hand the role back to the catalog.

    Only the flag is restored. The row is not deleted and its grants are not
    revoked: downgrading the schema is not a reason to take a working service
    account's access away, and re-adding `run_registrar` to ROLE_DEFINITIONS --
    which is what a real downgrade of this change means -- would reconcile the
    permission set at the next startup anyway.
    """
    op.get_bind().execute(
        sa.text("UPDATE role SET is_builtin = 1, updated_at = UTC_TIMESTAMP() "
                "WHERE name = :name"),
        {"name": ROLE_NAME},
    )
