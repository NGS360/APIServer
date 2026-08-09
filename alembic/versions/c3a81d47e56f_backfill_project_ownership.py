"""Backfill project membership from existing ownership attributes

Every project ends up with exactly one owner. Owners are derived from the data
already in projectattribute where that resolves to a real user; everything else
is adopted by the first user in the database, so no project is left
unadministrable.

Why a fallback rather than leaving projects ownerless: a project with no owner
cannot have its membership changed by anyone short of a superuser, and with the
numbers below that would be most of them.

The shape of the production data, measured before writing this:

    projects                                        11,043
    users                                              216
    distinct owner values in attributes              1,608
      of which resolve to an existing user             131
      which would need a shell user                  1,477

Coverage is limited by the users table, not by attribute quality --
`businessowner` is present on 10,798 projects but users only exist after first
login. Creating ~946 shell users for the username-shaped values was considered
and deliberately not done here: find_or_create_oauth_user matches on email only,
so a shell created without the exact corporate address is orphaned when the real
person signs in, and they become `username1` holding none of the grants. That
fix belongs with the shell-user work, not bolted onto a backfill.

Note the earlier claim in docs/RBAC.md that historical created_by is dominated by
a few bulk loaders is not supported: the distribution is long-tailed, topping out
at 5.4%. project.created_by resolves to a user for only 24.4% of projects, versus
~48% for the owner attributes, which is why attributes are preferred.

Idempotent: every insert is guarded by NOT EXISTS, and rows are tagged
source='migration' so the downgrade can remove exactly what this added.

Revision ID: c3a81d47e56f
Revises: b7c4e19f2a83
Create Date: 2026-08-09

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'c3a81d47e56f'
down_revision: Union[str, Sequence[str], None] = 'b7c4e19f2a83'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


OWNER_KEYS = ("'businessowner'", "'business owner'", "'dataowner'", "'data owner'")
ANALYST_KEYS = ("'ngsanalyst'", "'ngs analyst'", "'tbioanalyst'", "'tbio analyst'",
                "'createby'", "'createdby'")


def _role_id(conn, name: str):
    row = conn.execute(
        sa.text("SELECT id FROM role WHERE name = :n"), {"n": name}
    ).fetchone()
    if row is None:
        raise RuntimeError(
            f"role {name!r} is missing. The catalog is seeded at application "
            f"startup -- start the API against this database before migrating."
        )
    return row[0]


def _ownerless_count(conn, owner_role) -> int:
    return conn.execute(sa.text("""
        SELECT COUNT(*) FROM project p
        WHERE NOT EXISTS (
            SELECT 1 FROM project_member pm
            WHERE pm.project_id = p.id AND pm.role_id = :role
        )
    """), {"role": owner_role}).scalar()


def upgrade() -> None:
    conn = op.get_bind()

    owner_role = _role_id(conn, 'project_owner')
    contributor_role = _role_id(conn, 'project_contributor')

    owner_keys = ", ".join(OWNER_KEYS)
    analyst_keys = ", ".join(ANALYST_KEYS)

    # 1. Owners from the ownership attributes.
    #
    # A project can carry several owner-ish attributes; MIN(user id) picks one
    # deterministically so a re-run cannot pick a different person. Any
    # additional named owners are added as contributors in step 2.
    conn.execute(sa.text(f"""
        INSERT INTO project_member (id, project_id, user_id, role_id, source, granted_at)
        SELECT REPLACE(UUID(), '-', ''), t.project_id, t.user_id, :role, 'migration', NOW()
        FROM (
            SELECT pa.project_id, MIN(u.id) AS user_id
            FROM projectattribute pa
            JOIN users u ON LOWER(TRIM(u.username)) = LOWER(TRIM(pa.value))
            WHERE LOWER(TRIM(pa.`key`)) IN ({owner_keys})
            GROUP BY pa.project_id
        ) t
        WHERE NOT EXISTS (
            SELECT 1 FROM project_member pm
            WHERE pm.project_id = t.project_id AND pm.user_id = t.user_id
        )
    """), {"role": owner_role})

    # 2. Analysts and recorded creators become contributors, where they resolve
    #    and are not already a member.
    conn.execute(sa.text(f"""
        INSERT INTO project_member (id, project_id, user_id, role_id, source, granted_at)
        SELECT REPLACE(UUID(), '-', ''), t.project_id, t.user_id, :role, 'migration', NOW()
        FROM (
            SELECT DISTINCT pa.project_id, u.id AS user_id
            FROM projectattribute pa
            JOIN users u ON LOWER(TRIM(u.username)) = LOWER(TRIM(pa.value))
            WHERE LOWER(TRIM(pa.`key`)) IN ({analyst_keys})
        ) t
        WHERE NOT EXISTS (
            SELECT 1 FROM project_member pm
            WHERE pm.project_id = t.project_id AND pm.user_id = t.user_id
        )
    """), {"role": contributor_role})

    # 3. project.created_by, for projects that still have no owner.
    conn.execute(sa.text("""
        INSERT INTO project_member (id, project_id, user_id, role_id, source, granted_at)
        SELECT REPLACE(UUID(), '-', ''), t.id, t.user_id, :role, 'migration', NOW()
        FROM (
            SELECT p.id, u.id AS user_id
            FROM project p
            JOIN users u ON LOWER(TRIM(u.username)) = LOWER(TRIM(p.created_by))
            WHERE p.created_by IS NOT NULL AND p.created_by <> 'unknown'
        ) t
        WHERE NOT EXISTS (
            SELECT 1 FROM project_member pm
            WHERE pm.project_id = t.id AND pm.role_id = :role
        )
        AND NOT EXISTS (
            SELECT 1 FROM project_member pm2
            WHERE pm2.project_id = t.id AND pm2.user_id = t.user_id
        )
    """), {"role": owner_role})

    # 4. Whatever steps 1-3 could not resolve is adopted by the first user in the
    #    database. Under the original "first user registered wins" bootstrap that
    #    is the account holding superuser, so the adopter is both a real person
    #    and one who can already administer anything. Resolved at run time rather
    #    than hardcoded, so each tier adopts its own first user and no username is
    #    baked into the migration history.
    #
    #    id is the tiebreak, so the choice stays deterministic if two accounts
    #    share a created_at and a re-run cannot land on someone different.
    #
    #    Looked up only once there is something to adopt: on a fresh database
    #    -- CI, a new tier, a local container -- there are no projects and no
    #    users, and that must migrate cleanly rather than fail for want of an
    #    adopter nobody needs.
    if not _ownerless_count(conn, owner_role):
        return

    fallback = conn.execute(sa.text("""
        SELECT id, username FROM users ORDER BY created_at ASC, id ASC LIMIT 1
    """)).fetchone()
    if fallback is None:
        raise RuntimeError(
            "some projects could not be assigned an owner and there are no users "
            "in this database to adopt them"
        )
    fallback_id, fallback_username = fallback

    # 4a. Where the fallback account is already a member of an ownerless project
    #     -- it appears in some analyst attributes, so step 2 will have added it
    #     as a contributor -- promote that row instead of inserting a second one.
    #     UNIQUE(project_id, user_id) allows only one role per user per project,
    #     so an insert here would be skipped and the project left ownerless.
    conn.execute(sa.text("""
        UPDATE project_member pm
        SET pm.role_id = :role, pm.source = 'migration', pm.granted_at = NOW()
        WHERE pm.user_id = :uid
          AND pm.role_id <> :role
          AND NOT EXISTS (
              SELECT 1 FROM (SELECT * FROM project_member) pm2
              WHERE pm2.project_id = pm.project_id AND pm2.role_id = :role
          )
    """), {"uid": fallback_id, "role": owner_role})

    # 4b. Everything still ownerless goes to the fallback account, so that every
    #     project has someone who can administer it.
    conn.execute(sa.text("""
        INSERT INTO project_member (id, project_id, user_id, role_id, source, granted_at)
        SELECT REPLACE(UUID(), '-', ''), p.id, :uid, :role, 'migration', NOW()
        FROM project p
        WHERE NOT EXISTS (
            SELECT 1 FROM project_member pm
            WHERE pm.project_id = p.id AND pm.role_id = :role
        )
        AND NOT EXISTS (
            SELECT 1 FROM project_member pm2
            WHERE pm2.project_id = p.id AND pm2.user_id = :uid
        )
    """), {"uid": fallback_id, "role": owner_role})

    adopted = conn.execute(sa.text("""
        SELECT COUNT(*) FROM project_member pm
        WHERE pm.user_id = :uid AND pm.role_id = :role AND pm.source = 'migration'
    """), {"uid": fallback_id, "role": owner_role}).scalar()
    print(f"  {adopted} project(s) adopted by {fallback_username!r} "
          f"(first user in this database)")

    # Fail rather than leave a partially-owned estate behind.
    ownerless = _ownerless_count(conn, owner_role)
    if ownerless:
        raise RuntimeError(
            f"{ownerless} project(s) still have no owner after the backfill"
        )


def downgrade() -> None:
    """
    Remove only what this migration added.

    Scoped to source='migration' so grants made by hand afterwards survive.
    """
    op.get_bind().execute(
        sa.text("DELETE FROM project_member WHERE source = 'migration'")
    )
