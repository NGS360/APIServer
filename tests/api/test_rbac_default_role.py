""" Test cases for the default role granted at user creation """
import logging

import pytest
from sqlmodel import Session, select

from api.auth.models import UserRegister
from api.auth.services import register_user
from api.rbac.models import GrantSource, Role, UserRole
from api.rbac.seed import sync_rbac_catalog
from api.rbac.services import assign_default_roles
from core.config import get_settings


@pytest.fixture
def seeded(session: Session):
    sync_rbac_catalog(session)
    return session


@pytest.fixture
def default_role(monkeypatch):
    def _set(value: str):
        monkeypatch.setenv("DEFAULT_USER_ROLE", value)
        get_settings.cache_clear()
    return _set


def _roles_of(session: Session, username: str) -> list[str]:
    from api.auth.models import User

    user = session.exec(select(User).where(User.username == username)).one()
    return sorted(session.exec(
        select(Role.name).join(UserRole, UserRole.role_id == Role.id)
        .where(UserRole.user_id == user.id)
    ).all())


class TestConfig:

    def test_defaults_to_member(self, monkeypatch):
        monkeypatch.delenv("DEFAULT_USER_ROLE", raising=False)
        get_settings.cache_clear()
        assert get_settings().DEFAULT_USER_ROLE == "member"

    def test_can_be_pointed_at_another_role(self, default_role):
        default_role("auditor")
        assert get_settings().DEFAULT_USER_ROLE == "auditor"

    def test_none_disables_it(self, default_role):
        default_role("none")
        assert get_settings().DEFAULT_USER_ROLE == ""

    def test_an_empty_value_falls_through_to_the_default(self, default_role):
        """_get_config_value treats empty as unset, so DEFAULT_USER_ROLE= is
        absence, not "grant nothing". Disabling needs the explicit sentinel."""
        default_role("")
        assert get_settings().DEFAULT_USER_ROLE == "member"


class TestRegistration:
    """
    Each test registers a placeholder first: the legacy "first user registered
    wins" bootstrap makes the very first account a superuser, which would also
    pick up `admin` and obscure what is being asserted here.
    """

    @staticmethod
    def _existing(session):
        register_user(session, UserRegister(
            username="firstuser", email="firstuser@example.com",
            password="TestPassword123", full_name="First",
        ))

    def test_a_registered_user_receives_the_default_role(self, seeded):
        self._existing(seeded)
        register_user(seeded, UserRegister(
            username="newbie", email="newbie@example.com",
            password="TestPassword123", full_name="New Bie",
        ))
        assert _roles_of(seeded, "newbie") == ["member"]

    def test_the_grant_is_tagged_bootstrap(self, seeded):
        """So the downgrade can remove automatic grants without touching the
        ones an administrator made by hand."""
        self._existing(seeded)
        user = register_user(seeded, UserRegister(
            username="tagged", email="tagged@example.com",
            password="TestPassword123", full_name="Tagged",
        ))
        grant = seeded.exec(
            select(UserRole).where(UserRole.user_id == user.id)
        ).one()
        assert grant.source is GrantSource.BOOTSTRAP

    def test_no_default_role_configured_means_no_grant(self, seeded, default_role):
        self._existing(seeded)
        default_role("none")
        register_user(seeded, UserRegister(
            username="bare", email="bare@example.com",
            password="TestPassword123", full_name="Bare",
        ))
        assert _roles_of(seeded, "bare") == []

    def test_registration_survives_a_missing_role(self, session, default_role, caplog):
        """
        The catalog is deliberately NOT seeded here.

        Raising would fail the registration outright -- locking people out of the
        product because of an authorization misconfiguration. A user with no
        permissions is visible and fixable; a user who cannot sign up is not.
        """
        self._existing(session)
        default_role("does-not-exist")
        with caplog.at_level(logging.ERROR):
            user = register_user(session, UserRegister(
                username="survivor", email="survivor@example.com",
                password="TestPassword123", full_name="Survivor",
            ))
        assert user.id is not None
        assert _roles_of(session, "survivor") == []
        assert any("does-not-exist" in r.getMessage() for r in caplog.records)


class TestSuperusers:

    def test_a_superuser_also_receives_admin(self, seeded):
        from api.auth.models import User

        user = User(username="root2", email="root2@example.com",
                    is_active=True, is_verified=True, is_superuser=True)
        seeded.add(user)
        seeded.flush()
        granted = assign_default_roles(seeded, user)
        seeded.commit()
        assert sorted(granted) == ["admin", "member"]

    def test_an_ordinary_user_does_not(self, seeded):
        from api.auth.models import User

        user = User(username="plain", email="plain@example.com",
                    is_active=True, is_verified=True, is_superuser=False)
        seeded.add(user)
        seeded.flush()
        assert assign_default_roles(seeded, user) == ["member"]


class TestIdempotence:

    def test_granting_twice_does_not_duplicate(self, seeded):
        from api.auth.models import User

        user = User(username="twice", email="twice@example.com",
                    is_active=True, is_verified=True)
        seeded.add(user)
        seeded.flush()
        assert assign_default_roles(seeded, user) == ["member"]
        seeded.commit()
        assert assign_default_roles(seeded, user) == []
        seeded.commit()
        assert _roles_of(seeded, "twice") == ["member"]


class TestOAuthCreation:

    @staticmethod
    def _sso(session, email, provider_user_id, username):
        from api.auth.oauth2_service import find_or_create_oauth_user

        return find_or_create_oauth_user(
            session, "corp",
            {"provider_user_id": provider_user_id,
             "provider_username": username, "email": email,
             "name": "SSO User"},
            access_token="tok",
        )

    def test_an_sso_user_receives_the_default_role(self, seeded):
        """
        The path most users arrive by. Without a grant here, every SSO user hits
        403s on their first page under enforce.
        """
        register_user(seeded, UserRegister(
            username="firstuser", email="firstuser@example.com",
            password="TestPassword123", full_name="First",
        ))
        user = self._sso(seeded, "sso@example.com", "abc123", "ssouser")
        assert _roles_of(seeded, user.username) == ["member"]

    def test_the_very_first_sso_user_also_becomes_admin(self, seeded):
        """
        Documents the interaction with the legacy "first user registered wins"
        bootstrap rather than papering over it: on an empty database that account
        is made a superuser, so it picks up `admin` as well. docs/RBAC.md already
        flags that bootstrap as a privilege-escalation path to be replaced with
        BOOTSTRAP_ADMIN_USERNAMES.
        """
        user = self._sso(seeded, "first-sso@example.com", "first1", "firstsso")
        assert user.is_superuser is True
        assert _roles_of(seeded, user.username) == ["admin", "member"]
