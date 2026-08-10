""" Test cases for the permission guards now attached to routes """
import pytest

from core.config import get_settings


@pytest.fixture
def mode(monkeypatch):
    def _set(value: str):
        monkeypatch.setenv("RBAC_MODE", value)
        monkeypatch.setenv("ENVIRONMENT", "dev")
        get_settings.cache_clear()
    return _set


class TestGlobalPlaneGuards:
    """`client` holds the pre-RBAC set; `restricted_client` holds nothing."""

    def test_a_holder_is_allowed(self, client):
        assert client.post("/api/v1/projects", json={"name": "Guarded 1"}).status_code == 201

    def test_a_non_holder_is_refused(self, restricted_client):
        r = restricted_client.post("/api/v1/projects", json={"name": "Guarded 2"})
        assert r.status_code == 403
        assert "project:create" in r.json()["detail"]

    def test_the_refusal_happens_before_the_handler_runs(
        self, restricted_client, session
    ):
        """A guard that ran after the write would authorise nothing."""
        from sqlmodel import select

        from api.project.models import Project

        before = len(session.exec(select(Project)).all())
        restricted_client.post("/api/v1/projects", json={"name": "Guarded 3"})
        assert len(session.exec(select(Project)).all()) == before

    def test_dry_run_lets_a_non_holder_through(self, restricted_client, mode):
        mode("dry_run")
        r = restricted_client.post("/api/v1/projects",
                                   json={"name": "Guarded 4"})
        assert r.status_code == 201

    def test_off_lets_a_non_holder_through(self, restricted_client, mode):
        mode("off")
        r = restricted_client.post("/api/v1/projects",
                                   json={"name": "Guarded 5"})
        assert r.status_code == 201


class TestProjectPlaneGuards:

    def test_a_global_grant_covers_every_project(self, client, test_project):
        """
        Forced by the data model, and relied on by the service account: a
        flowcell spans projects and BatchJob has no project column, so a
        machine principal cannot be enrolled per project.
        """
        assert client.post(
            f"/api/v1/projects/{test_project.project_id}/samples",
            json={"sample_id": "S-1"},
        ).status_code in (200, 201)

    def test_a_non_member_without_a_global_grant_is_refused(
        self, restricted_client, test_project
    ):
        r = restricted_client.post(
            f"/api/v1/projects/{test_project.project_id}/samples",
            json={"sample_id": "S-2"},
        )
        assert r.status_code == 403
        assert "sample:create" in r.json()["detail"]
        assert test_project.project_id in r.json()["detail"]

    def test_a_project_role_grants_access_to_that_project(
        self, restricted_client, session, test_project
    ):
        from sqlmodel import select

        from api.auth.models import User
        from api.rbac.models import GrantSource, ProjectMember, Role

        user = session.exec(select(User).where(User.username == "norole")).one()
        role = session.exec(
            select(Role).where(Role.name == "project_contributor")
        ).one()
        session.add(ProjectMember(project_id=test_project.id, user_id=user.id,
                                  role_id=role.id, source=GrantSource.MANUAL))
        session.commit()

        assert restricted_client.post(
            f"/api/v1/projects/{test_project.project_id}/samples",
            json={"sample_id": "S-3"},
        ).status_code in (200, 201)

    def test_a_missing_project_is_404_not_403(self, restricted_client):
        """
        ProjectDep is declared as a sub-dependency precisely so the 404 is
        raised first: answering 403 for a project that does not exist leaks
        which project ids are real.
        """
        assert restricted_client.post(
            "/api/v1/projects/NO-SUCH-PROJECT/samples", json={"sample_id": "S-4"},
        ).status_code == 404


class TestRetainedSuperuserGates:
    """
    The superuser-only routes keep CurrentSuperuser *and* gain a guard.

    Dropping the existing gate in favour of the guard would have opened these
    to everyone for the length of the dry-run window, since dry-run allows what
    it would otherwise refuse. These tests pin that the gate is still there.
    """

    @pytest.mark.parametrize("mode_value", ["off", "dry_run", "enforce"])
    def test_settings_update_still_requires_a_superuser(
        self, client, mode, mode_value
    ):
        mode(mode_value)
        r = client.put("/api/v1/settings/DATA_BUCKET_URI",
                       json={"value": "s3://hijacked"})
        assert r.status_code == 403, mode_value

    @pytest.mark.parametrize("mode_value", ["off", "dry_run", "enforce"])
    def test_project_member_management_still_requires_a_superuser(
        self, client, test_project, mode, mode_value
    ):
        mode(mode_value)
        assert client.get(
            f"/api/v1/projects/{test_project.project_id}/members"
        ).status_code == 403, mode_value

    def test_a_superuser_still_passes(self, superuser_client, test_project):
        assert superuser_client.get(
            f"/api/v1/projects/{test_project.project_id}/members"
        ).status_code == 200


class TestSelfServiceIsUnguarded:

    def test_rbac_me_needs_no_permission(self, restricted_client):
        """A user with no roles must still be able to discover that."""
        r = restricted_client.get("/api/v1/rbac/me")
        assert r.status_code == 200
        assert r.json()["global_permissions"] == []
