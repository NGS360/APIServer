"""Make run_registrar and run_associator custom roles instead of builtin ones

Revision ID: c8e4a1f72b93
Revises: b4d17c3e9f52
Create Date: 2026-10-21

Both roles were removed from ROLE_DEFINITIONS in api/rbac/roles.py. That alone
is not enough, and the gap is the whole reason this migration exists:
sync_rbac_catalog() never deletes a role it no longer defines, so without this
the rows would survive in every tier still carrying `is_builtin = 1` -- roles
with no code definition behind them that update_role_permissions() and
delete_role() would both go on refusing. Stranded: uneditable through the API
and no longer re-derived from code either. Strictly worse than either state.

So this flips the flag, which is what actually hands the roles to
administrators.

Written to be idempotent and to not care what state the tier is in:

* **Row present** (every tier today -- production carries both, each with one
  permission and one grant, to the sequencer upload service and the run metrics
  lambda respectively): flip `is_builtin` to 0, touch nothing else. The
  permission rows and the grants are left exactly as they are, because
  converting a role must not disturb what it grants or who holds it. The
  description is deliberately not rewritten either -- an administrator may
  already have edited it.
* **Row absent** (a database created after this deploy, where the catalog sync
  will no longer make one): create it, with its permission row, so tiers do not
  drift. This is a one-time data seed, not an ownership claim -- nothing
  re-derives it afterwards.
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

_CUSTOM_NOTE = (
    "Custom role: owned by administrators through /rbac/roles, not re-derived "
    "from code on deploy."
)

# name, permission, display name, description
ROLES = (
    (
        "run_registrar",
        "run:create",
        "Run Registrar",
        "May register sequencing runs. Grants nothing else. " + _CUSTOM_NOTE,
    ),
    (
        "run_associator",
        "run:associate",
        "Run Associator",
        "May associate and dissociate samples and runs. Grants nothing else. "
        + _CUSTOM_NOTE,
    ),
)


def upgrade() -> None:
    conn = op.get_bind()

    for name, permission, display_name, description in ROLES:
        role_id = conn.execute(
            sa.text("SELECT id FROM role WHERE name = :name"), {"name": name}
        ).scalar()

        if role_id is None:
            role_id = uuid4().hex
            conn.execute(
                sa.text(
                    "INSERT INTO role "
                    "(id, name, display_name, description, scope, is_builtin, "
                    " created_at, updated_at) "
                    "VALUES (:id, :name, :display_name, :description, 'GLOBAL', "
                    " 0, UTC_TIMESTAMP(), UTC_TIMESTAMP())"
                ),
                {
                    "id": role_id,
                    "name": name,
                    "display_name": display_name,
                    "description": description,
                },
            )
        else:
            # The ordinary path. Only the flag moves -- not the description,
            # and emphatically not the permission rows or the grants.
            conn.execute(
                sa.text(
                    "UPDATE role SET is_builtin = 0, updated_at = UTC_TIMESTAMP() "
                    "WHERE id = :id AND is_builtin <> 0"
                ),
                {"id": role_id},
            )

        has_permission = conn.execute(
            sa.text("SELECT 1 FROM role_permission "
                    "WHERE role_id = :role_id AND permission = :permission"),
            {"role_id": role_id, "permission": permission},
        ).scalar()

        if not has_permission:
            conn.execute(
                sa.text("INSERT INTO role_permission (id, role_id, permission) "
                        "VALUES (:id, :role_id, :permission)"),
                {"id": uuid4().hex, "role_id": role_id,
                 "permission": permission},
            )


def downgrade() -> None:
    """
    Hand the roles back to the catalog.

    Only the flag is restored. The rows are not deleted and their grants are not
    revoked: downgrading the schema is not a reason to take a working service
    account's access away, and re-adding these names to ROLE_DEFINITIONS --
    which is what a real downgrade of this change means -- would reconcile the
    permission sets at the next startup anyway.
    """
    conn = op.get_bind()
    for name, _permission, _display_name, _description in ROLES:
        conn.execute(
            sa.text("UPDATE role SET is_builtin = 1, updated_at = UTC_TIMESTAMP() "
                    "WHERE name = :name"),
            {"name": name},
        )
