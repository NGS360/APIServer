"""
Tests for scripts/promote_superuser.py and the BOOTSTRAP_ADMIN_USERNAMES rule
that made it necessary.

The two belong together. Replacing "the first user to register becomes an
administrator" removed the only way a fresh database could produce a superuser,
and the RBAC admin API is itself guarded by CurrentSuperuser -- so without this
script a new tier has no route to a first administrator at all. The guard rails
are what is worth testing: superuser short-circuits every permission check ahead
of the resolver, so a mistake here is unbounded.
"""
import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from api.auth.models import User
from scripts import promote_superuser as script


@pytest.fixture(name="db")
def db_fixture(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    SQLModel.metadata.create_all(engine)
    monkeypatch.setattr(script, "engine", engine)
    monkeypatch.setattr(script, "confirm_target", lambda *a, **k: None)
    try:
        yield engine
    finally:
        engine.dispose()


@pytest.fixture(name="session")
def session_fixture(db):
    with Session(db) as s:
        yield s


def add_user(session, username, superuser=False):
    session.add(User(username=username, email=f"{username}@x.invalid",
                     is_active=True, is_verified=True, is_superuser=superuser))
    session.commit()


def run(monkeypatch, *argv):
    monkeypatch.setattr(script.sys, "argv", ["promote_superuser.py", *argv])
    return script.main()


def is_super(session, username):
    session.expire_all()
    return session.exec(
        select(User).where(User.username == username)
    ).one().is_superuser


class TestGranting:

    def test_it_grants(self, session, monkeypatch):
        add_user(session, "alice")
        assert run(monkeypatch, "--username", "alice", "--yes") == 0
        assert is_super(session, "alice") is True

    def test_an_unknown_user_is_an_error_not_a_silent_no_op(
        self, session, monkeypatch
    ):
        """
        Names the tier in the message, because accounts are per-tier and running
        against the wrong database is the likeliest cause.
        """
        add_user(session, "alice")
        with pytest.raises(SystemExit) as e:
            run(monkeypatch, "--username", "nobody", "--yes")
        assert "no user 'nobody'" in str(e.value)
        assert "tier" in str(e.value)

    def test_granting_twice_is_a_no_op(self, session, monkeypatch):
        add_user(session, "alice", superuser=True)
        assert run(monkeypatch, "--username", "alice", "--yes") == 0
        assert is_super(session, "alice") is True

    def test_dry_run_writes_nothing(self, session, monkeypatch):
        add_user(session, "alice")
        assert run(monkeypatch, "--username", "alice", "--dry-run") == 0
        assert is_super(session, "alice") is False


class TestRevoking:

    def test_it_revokes(self, session, monkeypatch):
        add_user(session, "alice", superuser=True)
        add_user(session, "bob", superuser=True)
        assert run(monkeypatch, "--username", "bob", "--revoke", "--yes") == 0
        assert is_super(session, "bob") is False
        assert is_super(session, "alice") is True

    def test_the_last_superuser_is_protected(self, session, monkeypatch):
        """
        Removing the last one leaves nobody who can grant it back through the
        API -- only this script, which needs direct database access. That is
        recoverable but not obvious, so it takes --force.
        """
        add_user(session, "alice", superuser=True)
        with pytest.raises(SystemExit) as e:
            run(monkeypatch, "--username", "alice", "--revoke", "--yes")
        assert "only superuser" in str(e.value)
        assert is_super(session, "alice") is True

    def test_force_overrides_that(self, session, monkeypatch, capsys):
        add_user(session, "alice", superuser=True)
        assert run(monkeypatch, "--username", "alice", "--revoke",
                   "--force", "--yes") == 0
        assert is_super(session, "alice") is False
        assert "no superuser" in capsys.readouterr().out

    def test_it_is_not_fooled_by_a_non_superuser_being_the_only_account(
        self, session, monkeypatch
    ):
        """The guard counts superusers, not users."""
        add_user(session, "alice", superuser=True)
        add_user(session, "bob")
        assert run(monkeypatch, "--username", "bob", "--revoke", "--yes") == 0


class TestListing:

    def test_list_reports_the_roster_and_writes_nothing(
        self, session, monkeypatch, capsys
    ):
        add_user(session, "alice", superuser=True)
        add_user(session, "bob")
        assert run(monkeypatch, "--list") == 0
        out = capsys.readouterr().out
        assert "alice" in out and "bob" not in out.split("superusers now")[1]

    def test_username_is_required_otherwise(self, session, monkeypatch):
        with pytest.raises(SystemExit):
            run(monkeypatch)


class TestTheBootstrapRuleItReplaced:

    def test_being_first_no_longer_grants_superuser(self):
        """
        The escalation path this closed: on an empty database, whoever registered
        first received a credential that short-circuits every permission check.
        It also raced -- two concurrent registrations could both see no users.
        """
        from api.auth.services import is_bootstrap_admin

        assert is_bootstrap_admin("anybody") is False

    def test_only_a_configured_username_qualifies(self, monkeypatch):
        from api.auth.services import is_bootstrap_admin
        from core import config

        monkeypatch.setenv("BOOTSTRAP_ADMIN_USERNAMES", "admin1,admin2")
        config.get_settings.cache_clear()
        try:
            assert is_bootstrap_admin("admin1") is True
            assert is_bootstrap_admin("ADMIN2") is True
            assert is_bootstrap_admin("someoneelse") is False
        finally:
            config.get_settings.cache_clear()

    def test_an_empty_setting_means_nobody(self, monkeypatch):
        """
        No fallback to first-user-wins. A fallback that restores the unsafe
        behaviour whenever the variable is unset is not a fix -- it is the same
        bug with an extra step.
        """
        from api.auth.services import is_bootstrap_admin
        from core import config

        monkeypatch.setenv("BOOTSTRAP_ADMIN_USERNAMES", "")
        config.get_settings.cache_clear()
        try:
            assert is_bootstrap_admin("anybody") is False
        finally:
            config.get_settings.cache_clear()

    def test_both_creation_sites_use_the_same_function(self):
        """
        A security decision duplicated in two files is one that will eventually
        differ between them -- which is how this rule survived in two copies.
        """
        import inspect

        from api.auth import oauth2_service, services

        assert "is_bootstrap_admin" in inspect.getsource(services.register_user)
        assert "is_bootstrap_admin" in inspect.getsource(
            oauth2_service.find_or_create_oauth_user
        )
