"""Backfill the default global role onto existing users

Every user created from now on gets `member` at creation. Users who predate that
hook hold nothing, and under RBAC_MODE=enforce holding nothing is a 403 on every
endpoint -- so without this the flip to enforce locks out effectively everyone.

Measured before writing this:

    tier      users   held a global role
    dev         130                    1
    staging     216                    1
    prod        217                    2

The two in prod are svc-batch-events and svc-rdc. Every human account, including
the 27 holding personal API keys, had none.

`member` is the pre-RBAC permission set: catalog reads, project:create, and the
read side of every resource. Granting it therefore changes nothing about what
anyone can do today -- it only makes the existing behaviour expressible as a
grant, which is what enforce needs.

Applied to all users rather than only active ones. A grant on a disabled account
is inert (is_active is checked upstream in get_current_active_user), whereas
skipping them leaves a trap: reactivating someone later would produce an account
with no permissions and no obvious reason why.

Superusers also receive `admin`. Inert today, since is_superuser short-circuits
ahead of roles; it exists so that removing the break-glass flag in a later
release cannot lock out the only accounts able to grant roles back.

Rows are tagged source='BOOTSTRAP' -- the same provenance assign_default_roles
writes at creation -- so the downgrade removes exactly the automatic grants and
leaves anything an administrator granted by hand.

Revision ID: e5f92c1b7d34
Revises: c3a81d47e56f
Create Date: 2026-08-10

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'e5f92c1b7d34'
down_revision: Union[str, Sequence[str], None] = 'c3a81d47e56f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Kept as a literal rather than read from settings: a migration has to mean the
# same thing on every replay, and DEFAULT_USER_ROLE is an environment variable
# that can differ per tier and change over time.
DEFAULT_ROLE = 'member'
SUPERUSER_ROLE = 'admin'


def _role_id(conn, name: str):
    row = conn.execute(
        sa.text("SELECT id FROM role WHERE name = :n"), {"n": name}
    ).fetchone()
    return row[0] if row else None


def _grant(conn, role_id, where: str) -> int:
    """
    Insert a user_role for everyone matching `where` who lacks it.

    NOT EXISTS makes it idempotent, and UNIQUE(user_id, role_id) would catch a
    race anyway.
    """
    result = conn.execute(sa.text(f"""
        INSERT INTO user_role (id, user_id, role_id, source, granted_at)
        SELECT REPLACE(UUID(), '-', ''), u.id, :role, 'BOOTSTRAP', NOW()
        FROM users u
        WHERE {where}
          AND NOT EXISTS (
              SELECT 1 FROM user_role ur
              WHERE ur.user_id = u.id AND ur.role_id = :role
          )
    """), {"role": role_id})
    return result.rowcount


def upgrade() -> None:
    conn = op.get_bind()

    users = conn.execute(sa.text("SELECT COUNT(*) FROM users")).scalar()
    if not users:
        # A fresh database -- CI, a new tier, a local container. Nothing to
        # backfill, and the role catalog may not be seeded yet either.
        return

    default_role = _role_id(conn, DEFAULT_ROLE)
    if default_role is None:
        raise RuntimeError(
            f"role {DEFAULT_ROLE!r} is missing. The catalog is seeded at "
            f"application startup -- start the API against this database before "
            f"migrating."
        )

    granted = _grant(conn, default_role, "1 = 1")
    print(f"  granted {DEFAULT_ROLE!r} to {granted} user(s)")

    superuser_role = _role_id(conn, SUPERUSER_ROLE)
    if superuser_role is not None:
        admins = _grant(conn, superuser_role, "u.is_superuser = 1")
        print(f"  granted {SUPERUSER_ROLE!r} to {admins} superuser(s)")

    # Every account must now resolve to at least one global role, or the flip to
    # enforce would deny it everything. Fail rather than leave that latent.
    without = conn.execute(sa.text("""
        SELECT COUNT(*) FROM users u
        WHERE NOT EXISTS (SELECT 1 FROM user_role ur WHERE ur.user_id = u.id)
    """)).scalar()
    if without:
        raise RuntimeError(
            f"{without} user(s) still hold no global role after the backfill"
        )


def downgrade() -> None:
    """
    Remove only the automatic grants.

    Scoped to source='BOOTSTRAP' so roles an administrator granted by hand
    survive. Note this cannot distinguish a grant made by this migration from
    one made by assign_default_roles at user creation -- both are bootstrap
    provenance by design, and both are the thing being undone.
    """
    op.get_bind().execute(
        sa.text("DELETE FROM user_role WHERE source = 'BOOTSTRAP'")
    )
