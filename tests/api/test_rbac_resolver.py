""" Test cases for permission resolution and the RBAC read endpoints """
import uuid

import pytest
from sqlmodel import Session, select

from api.auth.models import User
from api.rbac.models import ProjectMember, Role, UserRole
from api.rbac.permissions import ALL_PERMISSIONS, Permission
from api.rbac.resolver import AuthzContext
from api.rbac.seed import sync_rbac_catalog
from tests.conftest import LEGACY_ROLE_NAME, legacy_permissions


def _user(session: Session, username: str, superuser: bool = False) -> User:
    user = User(username=username, email=f"{username}@example.com",
                is_active=True, is_verified=True, is_superuser=superuser)
    session.add(user)
    session.commit()
    session.refresh(user)
    return user


def _role(session: Session, name: str) -> Role:
    return session.exec(select(Role).where(Role.name == name)).one()


def _grant_global(session: Session, user: User, role_name: str) -> None:
    session.add(UserRole(user_id=user.id, role_id=_role(session, role_name).id))
    session.commit()


def _grant_project(session: Session, user: User, project, role_name: str) -> None:
    session.add(ProjectMember(project_id=project.id, user_id=user.id,
                              role_id=_role(session, role_name).id))
    session.commit()


@pytest.fixture
def seeded(session: Session):
    sync_rbac_catalog(session)
    return session


class TestGlobalPlane:

    def test_no_roles_grants_nothing(self, seeded):
        ctx = AuthzContext.for_user(seeded, _user(seeded, "nobody"))
        assert not ctx.has(Permission.PROJECT_READ)
        assert ctx.effective_permissions() == []

    def test_a_granted_role_confers_its_permissions(self, seeded):
        user = _user(seeded, "reader")
        _grant_global(seeded, user, "member")
        ctx = AuthzContext.for_user(seeded, user)
        assert ctx.has(Permission.PROJECT_READ)
        assert ctx.has(Permission.JOB_SUBMIT)
        assert not ctx.has(Permission.SETTING_UPDATE)

    def test_grants_are_additive_across_roles(self, seeded):
        user = _user(seeded, "both")
        _grant_global(seeded, user, "member")
        _grant_global(seeded, user, "service_account")
        ctx = AuthzContext.for_user(seeded, user)
        assert ctx.has(Permission.CHAT_USE)      # only from member
        assert ctx.has(Permission.JOB_UPDATE)    # only from service_account

    def test_superuser_short_circuits_every_check(self, seeded):
        ctx = AuthzContext.for_user(seeded, _user(seeded, "root", superuser=True))
        for permission in ALL_PERMISSIONS:
            assert ctx.has(permission), permission

    def test_superuser_reports_every_permission(self, seeded):
        ctx = AuthzContext.for_user(seeded, _user(seeded, "root2", superuser=True))
        assert set(ctx.effective_permissions()) == {str(p) for p in ALL_PERMISSIONS}

    def test_revocation_takes_effect_on_the_next_request(self, seeded):
        """No cross-request caching, so a revoked grant is immediately gone."""
        user = _user(seeded, "revoked")
        _grant_global(seeded, user, "member")
        assert AuthzContext.for_user(seeded, user).has(Permission.PROJECT_READ)

        grant = seeded.exec(select(UserRole).where(UserRole.user_id == user.id)).one()
        seeded.delete(grant)
        seeded.commit()

        assert not AuthzContext.for_user(seeded, user).has(Permission.PROJECT_READ)


class TestProjectPlane:

    def test_project_role_grants_only_within_that_project(self, seeded, test_project):
        user = _user(seeded, "contributor")
        _grant_project(seeded, user, test_project, "project_contributor")
        ctx = AuthzContext.for_user(seeded, user)

        assert ctx.has_in_project(Permission.SAMPLE_CREATE, test_project.id)
        # A different project confers nothing.
        assert not ctx.has_in_project(Permission.SAMPLE_CREATE, uuid.uuid4())
        # And it is not a global grant.
        assert not ctx.has(Permission.SAMPLE_CREATE)

    def test_a_global_grant_applies_to_every_project(self, seeded, test_project):
        """Forced by the data model: a flowcell spans projects and the writeback
        account cannot be enrolled in every one."""
        user = _user(seeded, "lab")
        _grant_global(seeded, user, "lab_manager")
        ctx = AuthzContext.for_user(seeded, user)
        assert ctx.has_in_project(Permission.SAMPLE_CREATE, test_project.id)
        assert ctx.has_in_project(Permission.SAMPLE_CREATE, uuid.uuid4())

    def test_project_membership_is_memoised(self, seeded, test_project):
        user = _user(seeded, "cached")
        _grant_project(seeded, user, test_project, "project_viewer")
        ctx = AuthzContext.for_user(seeded, user)
        ctx.has_in_project(Permission.PROJECT_READ, test_project.id)
        ctx.has_in_project(Permission.FILE_READ, test_project.id)
        assert list(ctx._project_cache) == [test_project.id]

    def test_viewer_cannot_write(self, seeded, test_project):
        user = _user(seeded, "viewer")
        _grant_project(seeded, user, test_project, "project_viewer")
        ctx = AuthzContext.for_user(seeded, user)
        assert ctx.has_in_project(Permission.PROJECT_READ, test_project.id)
        assert not ctx.has_in_project(Permission.SAMPLE_DELETE, test_project.id)

    def test_owner_can_manage_members(self, seeded, test_project):
        user = _user(seeded, "owner")
        _grant_project(seeded, user, test_project, "project_owner")
        ctx = AuthzContext.for_user(seeded, user)
        assert ctx.has_in_project(Permission.PROJECT_MANAGE_MEMBERS, test_project.id)


class TestVisibleProjectIds:
    """None means unrestricted; an empty set means nothing. Conflating them would
    hide everything from the users who can see everything."""

    def test_none_when_the_permission_is_held_globally(self, seeded, test_project):
        user = _user(seeded, "globalreader")
        _grant_global(seeded, user, "member")   # member holds project:read globally
        assert AuthzContext.for_user(seeded, user).visible_project_ids() is None

    def test_none_for_a_superuser(self, seeded):
        ctx = AuthzContext.for_user(seeded, _user(seeded, "root3", superuser=True))
        assert ctx.visible_project_ids() is None

    def test_empty_set_when_the_user_can_see_nothing(self, seeded):
        ctx = AuthzContext.for_user(seeded, _user(seeded, "blind"))
        assert ctx.visible_project_ids() == set()

    def test_lists_only_projects_with_a_membership(self, seeded, test_project):
        user = _user(seeded, "scoped")
        _grant_project(seeded, user, test_project, "project_viewer")
        assert AuthzContext.for_user(seeded, user).visible_project_ids() == {
            test_project.id
        }

    def test_filters_by_the_requested_permission(self, seeded, test_project):
        """A viewer shows up for project:read but not for sample:delete."""
        user = _user(seeded, "scoped2")
        _grant_project(seeded, user, test_project, "project_viewer")
        ctx = AuthzContext.for_user(seeded, user)
        assert ctx.visible_project_ids(Permission.PROJECT_READ) == {test_project.id}
        assert ctx.visible_project_ids(Permission.SAMPLE_DELETE) == set()


class TestReadEndpoints:

    def test_permissions_catalog_requires_superuser(self, client):
        assert client.get("/api/v1/rbac/permissions").status_code == 403

    def test_permissions_catalog_lists_the_whole_catalog(self, superuser_client):
        response = superuser_client.get("/api/v1/rbac/permissions")
        assert response.status_code == 200
        body = response.json()
        assert len(body) == len(ALL_PERMISSIONS)
        entry = next(e for e in body if e["permission"] == "setting:update")
        assert entry["risk"] == "critical"
        assert entry["project_scopable"] is False

    def test_roles_requires_superuser(self, client):
        assert client.get("/api/v1/rbac/roles").status_code == 403

    def test_roles_lists_seeded_roles(self, superuser_client, session):
        sync_rbac_catalog(session)
        response = superuser_client.get("/api/v1/rbac/roles")
        assert response.status_code == 200
        names = {r["name"] for r in response.json()}
        assert {"member", "admin", "project_owner"} <= names

    def test_role_detail_includes_permissions(self, superuser_client, session):
        sync_rbac_catalog(session)
        body = superuser_client.get("/api/v1/rbac/roles/project_viewer").json()
        assert body["scope"] == "project"
        assert body["is_builtin"] is True
        assert "project:read" in body["permissions"]

    def test_unknown_role_is_404(self, superuser_client, session):
        sync_rbac_catalog(session)
        assert superuser_client.get("/api/v1/rbac/roles/nope").status_code == 404

    def test_me_reports_own_access(self, client, session):
        """Any authenticated user may see their own access."""
        sync_rbac_catalog(session)
        response = client.get("/api/v1/rbac/me")
        assert response.status_code == 200
        body = response.json()
        assert body["username"] == "testuser"
        assert body["is_superuser"] is False
        # The fixture user holds the pre-RBAC permission set, so this reports a
        # real grant rather than an empty one -- which is the point of the
        # endpoint. What matters is that it reports what the user actually has.
        assert body["global_roles"] == [LEGACY_ROLE_NAME]
        assert sorted(body["global_permissions"]) == legacy_permissions()

    def test_me_reports_everything_for_a_superuser(self, superuser_client, session):
        sync_rbac_catalog(session)
        body = superuser_client.get("/api/v1/rbac/me").json()
        assert body["is_superuser"] is True
        assert len(body["global_permissions"]) == len(ALL_PERMISSIONS)


class TestGuardFactories:
    """Construction-time validation, since these are built at import."""

    def test_require_permission_rejects_an_empty_argument_list(self):
        from api.rbac.deps import require_permission
        with pytest.raises(ValueError):
            require_permission()

    def test_project_guard_rejects_global_only_permissions(self):
        """A project role can never grant setting:update, so guarding a route
        with it would be a permanent, silent denial."""
        from api.rbac.deps import require_project_permission
        with pytest.raises(ValueError, match="project-scopable"):
            require_project_permission(Permission.SETTING_UPDATE)

    def test_project_guard_accepts_scopable_permissions(self):
        from api.rbac.deps import require_project_permission
        assert require_project_permission(Permission.SAMPLE_CREATE) is not None
