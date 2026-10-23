"""
`project:restrict` -- who may lock a project to its members, and unlock it.

The hole this closes. `restricted` is a field on `ProjectUpdate`, and
`PUT`/`PATCH /projects/{id}` is guarded on `project:update`, which is in
`member`. So every authenticated user could restrict every project, including
ones they had never touched -- and because the membership gate applies the
moment the flag is true, they generally could not undo it. An accidental flip on
somebody else's project had to be repaired by an administrator.

What is asserted here, in the order the tests appear:

* a `member` is refused, which is the fix;
* a `project_owner` is allowed, which is the "project creators" half -- the
  creator is granted that role in the same transaction as the project row;
* an administrator is allowed, which is the other half;
* a `project_contributor` is refused, which is the line this draws *inside* the
  project plane: `project:update` and `project:restrict` are not the same
  authority;
* an unchanged value is not a restriction change, so a client that reads a
  project and writes the whole object back is unaffected;
* the refusal survives `dry_run`, because `project:restrict` is `critical` and
  therefore in `ALWAYS_ENFORCE`. Without that the fix would have done nothing
  until the global flip, which is exactly the gap it exists to close.

RBAC_MODE is `enforce` in tests unless a test overrides it, so refusals are
403s.
"""
import pytest
from sqlmodel import select

from api.auth.models import User
from api.project.models import Project
from api.rbac.models import GrantSource, ProjectMember, Role
from api.rbac.permissions import Permission
from api.rbac.roles import ROLE_DEFINITIONS

URL = "/api/v1/projects/{project_id}"

# Both verbs carry the same two guards, so every test runs against both. They
# were wired separately, which is precisely how one of them would be missed.
METHODS = ("put", "patch")


def make_project(session, suffix: str, *, restricted: bool = False) -> Project:
    project = Project(
        project_id=f"P-20260101-{suffix}",
        name=f"Project {suffix}",
        created_by="someone-else",
        restricted=restricted,
    )
    session.add(project)
    session.commit()
    session.refresh(project)
    return project


def grant_project_role(session, project: Project, username: str, role_name: str):
    user = session.exec(select(User).where(User.username == username)).one()
    role = session.exec(select(Role).where(Role.name == role_name)).one()
    session.add(ProjectMember(project_id=project.id, user_id=user.id,
                              role_id=role.id, source=GrantSource.MANUAL))
    session.commit()


def send(client, method: str, project: Project, body: dict):
    return getattr(client, method)(
        URL.format(project_id=project.project_id), json=body
    )


@pytest.fixture(name="member_client")
def member_client_fixture(client_with_permissions):
    """
    A user holding exactly the `member` role's permissions and no project role.

    The ordinary user, in other words -- 258 of them in production. The whole
    point of the fixture is that it holds `project:update` and therefore reaches
    the route; if it were refused at the first guard these tests would prove
    nothing about the second.
    """
    return client_with_permissions(
        ROLE_DEFINITIONS["member"].permissions, username="plain-member"
    )


class TestTheCatalogEntry:
    """The two properties the behaviour below depends on."""

    def test_member_does_not_hold_it(self):
        assert Permission.PROJECT_RESTRICT not in ROLE_DEFINITIONS["member"].permissions

    def test_the_project_creator_s_role_holds_it(self):
        """
        `project_owner` is PROJECT_CREATOR_ROLE_NAME -- granted to the creator in
        the same transaction as the project insert -- so "project creators" needs
        no separate mechanism.
        """
        from api.rbac.roles import PROJECT_CREATOR_ROLE_NAME

        assert PROJECT_CREATOR_ROLE_NAME == "project_owner"
        assert (Permission.PROJECT_RESTRICT
                in ROLE_DEFINITIONS["project_owner"].permissions)
        assert (Permission.PROJECT_RESTRICT
                not in ROLE_DEFINITIONS["project_contributor"].permissions)

    def test_it_is_always_enforced(self):
        """
        Not decoration: this is what makes the guard bite in production, which
        runs `dry_run`. Derived from `critical` risk rather than hand-listed.
        """
        from api.rbac.mode import ALWAYS_ENFORCE
        from api.rbac.permissions import CATALOG

        assert CATALOG[Permission.PROJECT_RESTRICT].risk == "critical"
        assert Permission.PROJECT_RESTRICT in ALWAYS_ENFORCE


class TestWhoMayRestrict:

    @pytest.mark.parametrize("method", METHODS)
    def test_a_plain_member_is_refused(self, session, member_client, method):
        """The fix, stated once."""
        project = make_project(session, f"001{method[0]}")
        response = send(member_client, method, project, {"restricted": True})

        assert response.status_code == 403
        session.refresh(project)
        assert project.restricted is False

    @pytest.mark.parametrize("method", METHODS)
    def test_a_project_owner_is_allowed(
        self, session, restricted_client, method
    ):
        """
        `restricted_client` holds no global role at all, so anything it manages
        here came from the project plane -- which is the claim being tested.
        """
        project = make_project(session, f"002{method[0]}")
        grant_project_role(session, project, "norole", "project_owner")

        response = send(restricted_client, method, project, {"restricted": True})

        assert response.status_code == 200
        assert response.json()["restricted"] is True
        session.refresh(project)
        assert project.restricted is True

    @pytest.mark.parametrize("method", METHODS)
    def test_an_administrator_is_allowed(
        self, session, superuser_client, method
    ):
        project = make_project(session, f"003{method[0]}")

        response = send(superuser_client, method, project, {"restricted": True})

        assert response.status_code == 200
        session.refresh(project)
        assert project.restricted is True

    @pytest.mark.parametrize("method", METHODS)
    def test_a_project_contributor_is_refused(
        self, session, restricted_client, method
    ):
        """
        The line drawn inside the project plane. A contributor holds
        `project:update` on this project and so clears the route guard; it is
        the second check that stops it. Without this test, granting the new
        permission to `_PROJECT_CONTRIBUTOR` by mistake would pass the suite.
        """
        project = make_project(session, f"004{method[0]}")
        grant_project_role(session, project, "norole", "project_contributor")

        response = send(restricted_client, method, project, {"restricted": True})

        assert response.status_code == 403
        session.refresh(project)
        assert project.restricted is False


class TestUnlocking:
    """
    Clearing the flag is the same permission, deliberately. A control that is
    cheaper to turn on than off is how projects end up locked with nobody able
    to say why.
    """

    @pytest.mark.parametrize("method", METHODS)
    def test_an_owner_who_is_a_member_may_unlock(
        self, session, restricted_client, method
    ):
        project = make_project(session, f"005{method[0]}", restricted=True)
        grant_project_role(session, project, "norole", "project_owner")

        response = send(restricted_client, method, project, {"restricted": False})

        assert response.status_code == 200
        session.refresh(project)
        assert project.restricted is False

    @pytest.mark.parametrize("method", METHODS)
    def test_a_member_may_not_unlock(self, session, member_client, method):
        """
        Note this one is refused by the *route* guard, not by
        require_project_restrict: the project is already restricted and the
        caller is not a member, so require_project_permission stops it first.
        Asserted anyway, because "a member cannot quietly unlock a project"
        should not depend on which of the two guards happens to fire.
        """
        project = make_project(session, f"006{method[0]}", restricted=True)

        response = send(member_client, method, project, {"restricted": False})

        assert response.status_code == 403
        session.refresh(project)
        assert project.restricted is True

    @pytest.mark.parametrize("method", METHODS)
    def test_an_administrator_must_still_enrol_first(
        self, session, superuser_client, method
    ):
        """
        The documented recovery path, pinned so it is not mistaken for a bug.
        The membership gate in require_project_permission runs before this
        permission is consulted and exempts only `project:manage_members`, so an
        administrator reaching into a locked project enrols themselves and then
        acts -- two steps, leaving a project_member row behind, which is the
        point.
        """
        project = make_project(session, f"007{method[0]}", restricted=True)

        response = send(superuser_client, method, project, {"restricted": False})

        assert response.status_code == 403
        session.refresh(project)
        assert project.restricted is True

        # superuser_client does not seed the catalog -- it short-circuits ahead
        # of roles, so it has never needed the rows to exist.
        from api.rbac.seed import sync_rbac_catalog
        sync_rbac_catalog(session)

        grant_project_role(session, project, "admin", "project_owner")
        assert send(
            superuser_client, method, project, {"restricted": False}
        ).status_code == 200
        session.refresh(project)
        assert project.restricted is False


class TestTheCheckFiresOnlyOnAChange:
    """
    A client that GETs a project, edits one field and writes the whole object
    back echoes `restricted` unchanged. Refusing that would break ordinary
    editing for everyone who is not an owner, which is a far larger blast radius
    than the hole being closed.
    """

    @pytest.mark.parametrize("method", METHODS)
    def test_echoing_the_current_value_is_not_a_restriction_change(
        self, session, member_client, method
    ):
        project = make_project(session, f"008{method[0]}")

        response = send(member_client, method, project,
                        {"name": "Renamed", "restricted": False})

        assert response.status_code == 200
        assert response.json()["name"] == "Renamed"

    @pytest.mark.parametrize("method", METHODS)
    def test_omitting_the_field_is_not_a_restriction_change(
        self, session, member_client, method
    ):
        """Ordinary metadata editing, untouched."""
        project = make_project(session, f"009{method[0]}")

        response = send(member_client, method, project, {"name": "Renamed"})

        assert response.status_code == 200
        assert response.json()["name"] == "Renamed"

    @pytest.mark.parametrize("method", METHODS)
    def test_an_explicit_null_is_not_a_restriction_change(
        self, session, member_client, method
    ):
        """
        `None` is what the service treats as "not supplied", so the guard has to
        agree with it or the two drift apart.
        """
        project = make_project(session, f"010{method[0]}")

        response = send(member_client, method, project,
                        {"name": "Renamed", "restricted": None})

        assert response.status_code == 200
        session.refresh(project)
        assert project.restricted is False


class TestTheRefusalSurvivesDryRun:
    """
    Production runs `dry_run`, where a refusal is logged and the request
    proceeds. A guard that only bites under `enforce` would leave `restricted`
    settable by anyone until the global flip -- which is the whole of what this
    permission was added to prevent.

    `critical` risk puts it in ALWAYS_ENFORCE, which escalates `dry_run` to
    `enforce` for this check alone. `off` is not escalated, by design and
    consistently with every other permission: `off` means authorization is
    switched out.
    """

    @pytest.fixture
    def mode(self, monkeypatch):
        from core.config import get_settings

        def _set(value: str):
            monkeypatch.setenv("RBAC_MODE", value)
            monkeypatch.setenv("ENVIRONMENT", "dev")
            get_settings.cache_clear()
        yield _set
        get_settings.cache_clear()

    @pytest.mark.parametrize("mode_value", ["dry_run", "enforce"])
    @pytest.mark.parametrize("method", METHODS)
    def test_a_member_is_refused_in_dry_run_too(
        self, session, member_client, mode, mode_value, method
    ):
        project = make_project(session, f"011{method[0]}{mode_value[0]}")
        mode(mode_value)

        response = send(member_client, method, project, {"restricted": True})

        assert response.status_code == 403, mode_value
        session.refresh(project)
        assert project.restricted is False, mode_value
