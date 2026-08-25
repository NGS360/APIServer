"""
Tests for scripts/seed_rbac_catalog.py.

The script exists because the migration chain is not self-sufficient: two data
revisions read the RBAC role catalog, but the catalog is reconciled at application
startup by design, so `alembic upgrade head` on a fresh database fails with
"role 'project_owner' is missing". Seeding without booting the API is what makes a
new tier, a restored snapshot, or the CI migrations job possible.

sync_rbac_catalog is covered by the seeding tests. What is covered here is the
script around it: that it seeds an empty database at all, that a second run is a
no-op, that the tier guard is consulted before anything is written, and -- the
one with real teeth -- that the roles the backfill revisions look up by name are
actually among the roles it creates.
"""
import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, func, select

from api.rbac.models import Role, RolePermission
from scripts import seed_rbac_catalog as script


@pytest.fixture(name="db")
def db_fixture(monkeypatch):
    """
    A database of the script's own, with script.engine pointed at it.

    Deliberately not the shared `session` fixture: the script opens its own
    session and commits, so handing it one built elsewhere would test the fixture
    rather than the script.
    """
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    monkeypatch.setattr(script, "engine", engine)
    try:
        yield engine
    finally:
        engine.dispose()


@pytest.fixture(name="session")
def session_fixture(db):
    """Read-side session, for asserting what the script left behind."""
    with Session(db) as session:
        yield session


@pytest.fixture(name="run_script")
def run_script_fixture(monkeypatch):
    def run(*argv):
        monkeypatch.setattr(script.sys, "argv", ["seed_rbac_catalog.py", *argv])
        return script.main()

    return run


def counts(session):
    session.expire_all()
    return (
        session.exec(select(func.count()).select_from(Role)).one(),
        session.exec(select(func.count()).select_from(RolePermission)).one(),
    )


def test_seeds_an_empty_catalog(session, run_script):
    assert counts(session) == (0, 0)
    assert run_script("--yes") == 0
    roles, permissions = counts(session)
    assert roles > 0 and permissions > 0


def test_is_idempotent(session, run_script):
    """Startup runs this on every boot, and CI runs it mid-chain."""
    run_script("--yes")
    before = counts(session)
    assert run_script("--yes") == 0
    assert counts(session) == before


def test_writing_requires_the_tier_guard(session, run_script, monkeypatch):
    """
    Without --yes the tier prompt has to be consulted.

    Which database is written is decided entirely by SQLALCHEMY_DATABASE_URI, so
    this prompt is the only thing between seeding CI and seeding production.
    """
    called = []
    monkeypatch.setattr(script, "confirm_target",
                        lambda *a, **k: called.append(a[1]))
    run_script()
    assert called and "catalog" in called[0]


def test_a_stale_permission_is_removed(session, run_script):
    """
    Roles are upsert-never-delete, but permissions are reconciled: a permission
    dropped from roles.py has to leave the database, or a role keeps granting
    something the catalog no longer defines.
    """
    run_script("--yes")
    role = session.exec(select(Role).where(Role.name == "member")).one()
    session.add(RolePermission(role_id=role.id, permission="bogus:permission"))
    session.commit()

    run_script("--yes")

    session.expire_all()
    stale = session.exec(
        select(RolePermission).where(RolePermission.permission == "bogus:permission")
    ).all()
    assert stale == []


def test_the_backfill_revisions_have_the_roles_they_look_up(session, run_script):
    """
    The reason the script exists, as an assertion.

    c3a81d47e56f resolves 'project_owner' and 'project_contributor';
    e5f92c1b7d34 resolves 'member' and 'admin'. Each raises RuntimeError if its
    role is absent, so renaming one in roles.py without touching the revision
    breaks `alembic upgrade head` on every fresh database. That failure otherwise
    surfaces only in the CI migrations job, which needs a MySQL service
    container; this catches the rename in the ordinary suite.
    """
    run_script("--yes")
    names = set(session.exec(select(Role.name)).all())
    assert {"project_owner", "project_contributor", "member", "admin"} <= names
