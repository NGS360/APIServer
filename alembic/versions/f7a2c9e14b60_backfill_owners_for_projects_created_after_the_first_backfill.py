"""Backfill owners for projects created after the first ownership backfill

Revision ID: f7a2c9e14b60
Revises: e5f92c1b7d34
Create Date: 2026-08-29

`POST /projects` was supposed to grant the creator `project_owner` in the same
transaction as the project insert -- docs/RBAC.md has required it since the design
was written -- and it never did. c3a81d47e56f gave owners to every project that
existed when it ran; every project created since has **no members at all**, not
even the person who created it.

The omission is invisible until permissions are enforced, which is why it survived
this long. It surfaced in the production dry-run log: the single largest source of
would_deny from a real user was someone downloading FASTQs from a project created
two days earlier, refused because nobody was a member of it. The population grows
by every project created.

The code fix is in api/project/services.py. This revision covers the gap it cannot
reach backwards into.

Deliberately narrower than c3a81d47e56f. That revision had four escalating
strategies ending in adoption by the first user in the database, because it had to
leave no project ownerless. This one only resolves `project.created_by` against
`users.username`, because these projects were created *through the API by an
authenticated caller*, so created_by is a real username rather than the free-text
historical values the first backfill had to cope with. A project whose creator
cannot be resolved is reported and left alone: inventing an owner for a project
created last week is worse than a grant request, since somebody knows whose it is.

Tagged source='MIGRATION' *and* granted_by = the owner's own id, which is what
makes the downgrade exact. c3a81d47e56f uses the same source tag and leaves
granted_by NULL, so deleting on source alone would remove the first backfill's
grants too -- locking out everyone it had enrolled. The pair is the discriminator,
and "the creator granted it to themselves" is literally what happened.
"""
from alembic import op
import sqlalchemy as sa


revision = 'f7a2c9e14b60'
down_revision = 'e5f92c1b7d34'
branch_labels = None
depends_on = None


# SQLAlchemy's Enum stores the member NAME, not the value, so the column holds
# 'MIGRATION' rather than 'migration'. Matching the wrong case silently inserts
# nothing on a case-sensitive collation and, worse, makes the downgrade a no-op.
_SOURCE = 'MIGRATION'


def _role_id(conn, name):
    row = conn.execute(
        sa.text("SELECT id FROM role WHERE name = :name"), {"name": name}
    ).fetchone()
    if row is None:
        raise RuntimeError(
            f"role {name!r} is missing. The catalog is seeded at application "
            f"startup -- start the API against this database before migrating, "
            f"or run scripts/seed_rbac_catalog.py."
        )
    return row[0]


def upgrade() -> None:
    conn = op.get_bind()

    ownerless = conn.execute(sa.text("""
        SELECT COUNT(*) FROM project p
        WHERE NOT EXISTS (
            SELECT 1 FROM project_member pm WHERE pm.project_id = p.id
        )
    """)).scalar()

    if not ownerless:
        # Nothing to do. Notably the case on a fresh database, where the CI
        # migrations job runs this against no rows at all.
        return

    owner_role = _role_id(conn, 'project_owner')

    conn.execute(sa.text("""
        INSERT INTO project_member
               (id, project_id, user_id, role_id, source, granted_at, granted_by)
        SELECT REPLACE(UUID(), '-', ''), t.id, t.user_id, :role, :source, NOW(),
               t.user_id
        FROM (
            SELECT p.id, u.id AS user_id
            FROM project p
            JOIN users u
              ON LOWER(TRIM(u.username)) = LOWER(TRIM(p.created_by))
            WHERE p.created_by IS NOT NULL
              AND p.created_by <> 'unknown'
              AND NOT EXISTS (
                  SELECT 1 FROM project_member pm WHERE pm.project_id = p.id
              )
        ) t
    """), {"role": owner_role, "source": _SOURCE})

    remaining = conn.execute(sa.text("""
        SELECT p.project_id, p.created_by FROM project p
        WHERE NOT EXISTS (
            SELECT 1 FROM project_member pm WHERE pm.project_id = p.id
        )
        ORDER BY p.created_at DESC
        LIMIT 50
    """)).fetchall()

    if remaining:
        # Reported rather than adopted. Somebody knows whose these are, and a
        # wrong owner on a recent project is harder to notice than a missing one.
        print(
            f"\n{len(remaining)} project(s) still have no member; created_by "
            f"does not resolve to a user. These need a grant by hand:"
        )
        for project_id, created_by in remaining:
            print(f"  {project_id}  created_by={created_by!r}")
        print()


def downgrade() -> None:
    # source alone is NOT enough: c3a81d47e56f tags its grants 'MIGRATION' as
    # well, and deleting those would lock out every user it enrolled. Its rows
    # leave granted_by NULL; this revision sets it to the owner's own id, so the
    # pair identifies exactly what was added here.
    op.get_bind().execute(
        sa.text("""
            DELETE FROM project_member
            WHERE source = :source AND granted_by IS NOT NULL
              AND granted_by = user_id
        """),
        {"source": _SOURCE},
    )
