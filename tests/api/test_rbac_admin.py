""" Test cases for RBAC role and grant mutations """
import pytest
from sqlmodel import Session, select

from api.auth.models import User
from api.rbac.models import ProjectMember, Role, UserRole
from api.rbac.seed import sync_rbac_catalog


@pytest.fixture
def seeded(session: Session):
    sync_rbac_catalog(session)
    return session


def _user(session: Session, username: str, superuser: bool = False) -> User:
    user = User(username=username, email=f"{username}@example.com",
                is_active=True, is_verified=True, is_superuser=superuser)
    session.add(user)
    session.commit()
    session.refresh(user)
    return user


class TestRoleCreation:

    def test_creates_a_custom_role(self, superuser_client, seeded):
        r = superuser_client.post("/api/v1/rbac/roles", json={
            "name": "reviewer", "display_name": "Reviewer",
            "scope": "global", "permissions": ["project:read", "qcrecord:read"],
        })
        assert r.status_code == 201
        assert r.json()["is_builtin"] is False
        assert sorted(r.json()["permissions"]) == ["project:read", "qcrecord:read"]

    def test_rejects_a_duplicate_name(self, superuser_client, seeded):
        assert superuser_client.post("/api/v1/rbac/roles", json={
            "name": "member", "display_name": "Dup",
            "scope": "global", "permissions": [],
        }).status_code == 409

    def test_rejects_an_unknown_permission(self, superuser_client, seeded):
        r = superuser_client.post("/api/v1/rbac/roles", json={
            "name": "bogus", "display_name": "Bogus",
            "scope": "global", "permissions": ["project:archive"],
        })
        assert r.status_code == 422
        assert "project:archive" in r.json()["detail"]

    def test_rejects_global_only_permissions_on_a_project_role(
        self, superuser_client, seeded
    ):
        """The project plane can never honour setting:update, so accepting it
        would create a permission that silently does nothing."""
        r = superuser_client.post("/api/v1/rbac/roles", json={
            "name": "proj_bad", "display_name": "Bad",
            "scope": "project", "permissions": ["setting:update"],
        })
        assert r.status_code == 422
        assert "setting:update" in r.json()["detail"]

    def test_requires_superuser(self, client, seeded):
        assert client.post("/api/v1/rbac/roles", json={
            "name": "x", "display_name": "X", "scope": "global", "permissions": [],
        }).status_code == 403


class TestRoleEditing:

    def test_replaces_the_permission_set(self, superuser_client, seeded):
        superuser_client.post("/api/v1/rbac/roles", json={
            "name": "editable", "display_name": "E",
            "scope": "global", "permissions": ["project:read"],
        })
        r = superuser_client.patch("/api/v1/rbac/roles/editable",
                                   json={"permissions": ["run:read"]})
        assert r.status_code == 200
        assert r.json()["permissions"] == ["run:read"]

    def test_refuses_to_edit_a_builtin_role(self, superuser_client, seeded):
        """Builtin permissions are re-derived on every deploy, so an edit here
        would be silently undone rather than persisted."""
        r = superuser_client.patch("/api/v1/rbac/roles/member",
                                   json={"permissions": ["project:read"]})
        assert r.status_code == 409
        assert "builtin" in r.json()["detail"]

    def test_unknown_role_is_404(self, superuser_client, seeded):
        assert superuser_client.patch("/api/v1/rbac/roles/ghost",
                                      json={"permissions": []}).status_code == 404


class TestRoleDeletion:

    def test_deletes_an_unused_custom_role(self, superuser_client, seeded):
        superuser_client.post("/api/v1/rbac/roles", json={
            "name": "temp", "display_name": "T", "scope": "global", "permissions": [],
        })
        assert superuser_client.delete("/api/v1/rbac/roles/temp").status_code == 204
        assert superuser_client.get("/api/v1/rbac/roles/temp").status_code == 404

    def test_refuses_to_delete_a_builtin_role(self, superuser_client, seeded):
        assert superuser_client.delete("/api/v1/rbac/roles/admin").status_code == 409

    def test_refuses_to_delete_a_granted_role(self, superuser_client, seeded):
        """Deleting it would cascade the grants away, silently revoking access."""
        superuser_client.post("/api/v1/rbac/roles", json={
            "name": "granted", "display_name": "G", "scope": "global",
            "permissions": ["project:read"],
        })
        _user(seeded, "holder")
        superuser_client.post("/api/v1/rbac/users/holder/roles",
                              json={"role": "granted"})
        r = superuser_client.delete("/api/v1/rbac/roles/granted")
        assert r.status_code == 409
        assert "still granted" in r.json()["detail"]


class TestGlobalGrants:

    def test_grants_and_lists(self, superuser_client, seeded):
        _user(seeded, "alice")
        r = superuser_client.post("/api/v1/rbac/users/alice/roles",
                                  json={"role": "lab_manager"})
        assert r.status_code == 200
        assert "lab_manager" in r.json()

    def test_granting_twice_is_idempotent(self, superuser_client, seeded):
        _user(seeded, "bob")
        superuser_client.post("/api/v1/rbac/users/bob/roles", json={"role": "member"})
        r = superuser_client.post("/api/v1/rbac/users/bob/roles",
                                  json={"role": "member"})
        assert r.status_code == 200
        assert r.json().count("member") == 1

    def test_rejects_a_project_role_on_the_global_endpoint(
        self, superuser_client, seeded
    ):
        _user(seeded, "carol")
        r = superuser_client.post("/api/v1/rbac/users/carol/roles",
                                  json={"role": "project_owner"})
        assert r.status_code == 400
        assert "project role" in r.json()["detail"]

    def test_revokes(self, superuser_client, seeded):
        _user(seeded, "dave")
        superuser_client.post("/api/v1/rbac/users/dave/roles", json={"role": "member"})
        r = superuser_client.delete("/api/v1/rbac/users/dave/roles/member")
        assert r.status_code == 200
        assert r.json() == []

    def test_revoking_something_not_held_is_404(self, superuser_client, seeded):
        _user(seeded, "erin")
        assert superuser_client.delete(
            "/api/v1/rbac/users/erin/roles/member"
        ).status_code == 404

    def test_unknown_user_is_404(self, superuser_client, seeded):
        assert superuser_client.post("/api/v1/rbac/users/nobody/roles",
                                     json={"role": "member"}).status_code == 404


class TestLastRoleManagerGuard:
    """Losing the last role manager means nobody can grant anything back without
    a superuser or direct database access."""

    def test_refuses_to_revoke_the_last_role_manager(self, superuser_client, seeded):
        _user(seeded, "onlyadmin")
        superuser_client.post("/api/v1/rbac/users/onlyadmin/roles",
                              json={"role": "admin"})
        r = superuser_client.delete("/api/v1/rbac/users/onlyadmin/roles/admin")
        assert r.status_code == 409
        assert "last non-superuser holder" in r.json()["detail"]

    def test_allows_revoking_when_another_holder_exists(
        self, superuser_client, seeded
    ):
        _user(seeded, "admin1")
        _user(seeded, "admin2")
        superuser_client.post("/api/v1/rbac/users/admin1/roles", json={"role": "admin"})
        superuser_client.post("/api/v1/rbac/users/admin2/roles", json={"role": "admin"})
        assert superuser_client.delete(
            "/api/v1/rbac/users/admin1/roles/admin"
        ).status_code == 200

    def test_superusers_do_not_count_as_holders(self, superuser_client, seeded):
        """A superuser bypasses roles entirely, so they cannot be the safety net
        that makes revoking the last real holder safe."""
        _user(seeded, "root", superuser=True)
        _user(seeded, "onlyadmin2")
        superuser_client.post("/api/v1/rbac/users/root/roles", json={"role": "admin"})
        superuser_client.post("/api/v1/rbac/users/onlyadmin2/roles",
                              json={"role": "admin"})
        assert superuser_client.delete(
            "/api/v1/rbac/users/onlyadmin2/roles/admin"
        ).status_code == 409


class TestProjectMembership:

    def test_adds_and_lists_a_member(self, superuser_client, seeded, test_project):
        _user(seeded, "frank")
        r = superuser_client.post(
            f"/api/v1/projects/{test_project.project_id}/members",
            json={"username": "frank", "role": "project_viewer"},
        )
        assert r.status_code == 200
        assert r.json()[0]["username"] == "frank"
        assert r.json()[0]["role"] == "project_viewer"

    def test_changes_an_existing_member_role(
        self, superuser_client, seeded, test_project
    ):
        _user(seeded, "grace")
        base = f"/api/v1/projects/{test_project.project_id}/members"
        superuser_client.post(base, json={"username": "grace",
                                          "role": "project_viewer"})
        r = superuser_client.post(base, json={"username": "grace",
                                              "role": "project_contributor"})
        assert [m["role"] for m in r.json()] == ["project_contributor"]

    def test_rejects_a_global_role(self, superuser_client, seeded, test_project):
        _user(seeded, "heidi")
        r = superuser_client.post(
            f"/api/v1/projects/{test_project.project_id}/members",
            json={"username": "heidi", "role": "lab_manager"},
        )
        assert r.status_code == 400
        assert "global role" in r.json()["detail"]

    def test_removes_a_member(self, superuser_client, seeded, test_project):
        _user(seeded, "ivan")
        base = f"/api/v1/projects/{test_project.project_id}/members"
        superuser_client.post(base, json={"username": "ivan",
                                          "role": "project_viewer"})
        r = superuser_client.delete(f"{base}/ivan")
        assert r.status_code == 200
        assert r.json() == []

    def test_requires_superuser(self, client, seeded, test_project):
        assert client.get(
            f"/api/v1/projects/{test_project.project_id}/members"
        ).status_code == 403


class TestLastOwnerGuard:
    """An ownerless project cannot have its membership changed by anyone short of
    a superuser, which is how projects quietly become unadministrable."""

    def test_refuses_to_remove_the_last_owner(
        self, superuser_client, seeded, test_project
    ):
        _user(seeded, "owner1")
        base = f"/api/v1/projects/{test_project.project_id}/members"
        superuser_client.post(base, json={"username": "owner1",
                                          "role": "project_owner"})
        r = superuser_client.delete(f"{base}/owner1")
        assert r.status_code == 409
        assert "last owner" in r.json()["detail"]

    def test_refuses_to_demote_the_last_owner(
        self, superuser_client, seeded, test_project
    ):
        _user(seeded, "owner2")
        base = f"/api/v1/projects/{test_project.project_id}/members"
        superuser_client.post(base, json={"username": "owner2",
                                          "role": "project_owner"})
        r = superuser_client.post(base, json={"username": "owner2",
                                              "role": "project_viewer"})
        assert r.status_code == 409

    def test_allows_removing_an_owner_when_another_remains(
        self, superuser_client, seeded, test_project
    ):
        _user(seeded, "owner3")
        _user(seeded, "owner4")
        base = f"/api/v1/projects/{test_project.project_id}/members"
        superuser_client.post(base, json={"username": "owner3",
                                          "role": "project_owner"})
        superuser_client.post(base, json={"username": "owner4",
                                          "role": "project_owner"})
        assert superuser_client.delete(f"{base}/owner3").status_code == 200

    def test_removing_a_non_owner_is_unaffected(
        self, superuser_client, seeded, test_project
    ):
        _user(seeded, "owner5")
        _user(seeded, "viewer5")
        base = f"/api/v1/projects/{test_project.project_id}/members"
        superuser_client.post(base, json={"username": "owner5",
                                          "role": "project_owner"})
        superuser_client.post(base, json={"username": "viewer5",
                                          "role": "project_viewer"})
        assert superuser_client.delete(f"{base}/viewer5").status_code == 200


class TestGrantsSurviveSeeding:

    def test_a_reseed_does_not_disturb_grants(self, superuser_client, seeded,
                                              test_project):
        _user(seeded, "persist")
        superuser_client.post("/api/v1/rbac/users/persist/roles",
                              json={"role": "member"})
        superuser_client.post(
            f"/api/v1/projects/{test_project.project_id}/members",
            json={"username": "persist", "role": "project_viewer"},
        )
        sync_rbac_catalog(seeded)
        assert len(seeded.exec(select(UserRole)).all()) == 1
        assert len(seeded.exec(select(ProjectMember)).all()) == 1
        assert seeded.exec(select(Role).where(Role.name == "member")).first()


class TestProjectResponseCarriesCallerPermissions:
    """
    GET /projects/{project_id} reports what the caller may do in that project.

    This is the only place that answer exists: /rbac/me carries the global plane
    only, so without this a UI has no way to gate a project control except by
    making the request and handling the refusal.
    """

    def test_a_superuser_holds_every_scopable_permission(
        self, superuser_client, test_project
    ):
        from api.rbac.permissions import PROJECT_SCOPABLE

        body = superuser_client.get(
            f"/api/v1/projects/{test_project.project_id}"
        ).json()
        assert set(body["permissions"]) == {str(p) for p in PROJECT_SCOPABLE}

    def test_a_project_owner_holds_manage_members(
        self, project_owner_client, test_project
    ):
        body = project_owner_client.get(
            f"/api/v1/projects/{test_project.project_id}"
        ).json()
        assert "project:manage_members" in body["permissions"]

    def test_a_project_grant_does_not_reach_another_project(
        self, project_owner_client, other_project
    ):
        """The grant is per project, so the report has to be too."""
        body = project_owner_client.get(
            f"/api/v1/projects/{other_project.project_id}"
        ).json()
        assert "project:manage_members" not in body["permissions"]

    def test_a_global_grant_is_included(self, client, test_project):
        """
        has_in_project is global OR project, so the report must be too.

        Reporting only the membership-derived grants would show a caller holding
        a global role as having nothing in the project, and a UI gating on this
        would hide every control from them.
        """
        body = client.get(f"/api/v1/projects/{test_project.project_id}").json()
        assert "sample:create" in body["permissions"]
        assert "project:manage_members" not in body["permissions"]

    def test_only_scopable_permissions_are_reported(
        self, superuser_client, test_project
    ):
        """
        A project role can never carry the rest, so reporting them per project
        would invite reading the absence of `setting:update` as something the
        project had to say about it.
        """
        body = superuser_client.get(
            f"/api/v1/projects/{test_project.project_id}"
        ).json()
        assert "setting:update" not in body["permissions"]
        assert "role:manage" not in body["permissions"]

    def test_an_anonymous_caller_gets_null_not_empty(
        self, unauthenticated_client, test_project
    ):
        """
        None means nobody was asking; [] would claim this caller was evaluated
        and holds nothing. The route is still reachable anonymously, so the
        distinction is reachable too.
        """
        body = unauthenticated_client.get(
            f"/api/v1/projects/{test_project.project_id}"
        ).json()
        assert body["permissions"] is None

    def test_the_list_route_does_not_populate_it(self, superuser_client, test_project):
        """
        Left None on the list, like sequencing_runs: resolving it per row is an
        N+1 for something no list view needs.
        """
        rows = superuser_client.get("/api/v1/projects").json()["data"]
        assert rows
        assert all(row["permissions"] is None for row in rows)
