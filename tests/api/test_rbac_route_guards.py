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

    def test_a_graduated_permission_is_enforced_even_in_dry_run(
        self, restricted_client, mode
    ):
        """
        project:create was graduated to enforce on 2026-09-15, on the evidence
        of zero would_deny across a 28-day window. So dry-run refuses it.

        This test used to assert the opposite -- that dry-run let a non-holder
        create a project -- and it failed when the graduation landed. It is
        kept pointed at this route deliberately: it is now the end-to-end check
        that graduating a permission actually changes behaviour on a real route,
        which is the whole point of the mechanism.
        """
        mode("dry_run")
        r = restricted_client.post("/api/v1/projects",
                                   json={"name": "Guarded 4"})
        assert r.status_code == 403

    def test_dry_run_still_lets_a_non_holder_through_elsewhere(
        self, restricted_client, mode
    ):
        """
        The property the previous test used to carry: a permission that has not
        been graduated is still only logged, not refused.

        Uses manifest:read, which is in dry-run because two callers surfaced
        after those routes closed on 09-11. When it graduates this will start
        failing -- at which point move it to another non-graduated permission
        rather than deleting it, because "dry-run does not refuse" has to stay
        covered for as long as any permission is in dry-run.
        """
        mode("dry_run")
        r = restricted_client.get("/api/v1/manifest",
                                  params={"s3_path": "s3://bucket/prefix/"})
        assert r.status_code != 403, (
            "manifest:read appears to have been graduated -- repoint this test "
            "at a permission still in dry-run"
        )

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


class TestTheAdminSurfaceHoldsOnItsGuardAlone:
    """
    These routes carried `CurrentSuperuser` as well as a permission guard. The
    flag came off on 2026-09-18, because while it gated them `is_superuser`
    could not be removed from the three personal accounts that hold it -- doing
    so would have cost the owner the admin API.

    The flag was doing real work, and the tests here previously pinned that: a
    guard only *logs* in dry-run, so removing the flag without another change
    would have opened these to every authenticated user in production.

    What replaced it is the risk level. `setting:update` and `role:manage` were
    already `critical`; `project:manage_members` was raised to `critical` in the
    same change, on the reasoning that project membership is the project-level
    grant plane. `critical` means ALWAYS_ENFORCE, which refuses even in dry-run.

    So the property is preserved for `dry_run` and `enforce` by the guard alone.
    It is *not* preserved for `off` -- see the test below, which is the honest
    record of what this change cost.
    """

    @pytest.mark.parametrize("mode_value", ["dry_run", "enforce"])
    def test_settings_update_refuses_a_non_holder(self, client, mode, mode_value):
        mode(mode_value)
        r = client.put("/api/v1/settings/DATA_BUCKET_URI",
                       json={"value": "s3://hijacked"})
        assert r.status_code == 403, mode_value

    @pytest.mark.parametrize("mode_value", ["dry_run", "enforce"])
    def test_member_management_refuses_a_non_holder(
        self, client, test_project, mode, mode_value
    ):
        mode(mode_value)
        assert client.get(
            f"/api/v1/projects/{test_project.project_id}/members"
        ).status_code == 403, mode_value

    @pytest.mark.parametrize("route", [
        "/api/v1/projects/{project_id}/members",
    ])
    def test_off_mode_no_longer_protects_the_admin_surface(
        self, client, test_project, mode, route
    ):
        """
        What removing the flag cost, asserted rather than left implicit.

        `off` means "do not check; every caller is allowed through" -- it is
        documented as an escape hatch for local work and explicitly not the
        rollback plan. ALWAYS_ENFORCE escalates *dry_run* to enforce and does
        not escalate `off`, so with RBAC_MODE=off these routes are now reachable
        by any authenticated user. The `CurrentSuperuser` dependency used to
        hold here because it is an authentication-layer check that no mode
        affects.

        Production runs `dry_run`, where the critical risk level keeps them
        refused. This is a local-development exposure, and it is pinned so that
        the trade is visible rather than discovered.
        """
        mode("off")
        r = client.get(route.format(project_id=test_project.project_id))
        assert r.status_code == 200, (
            "off mode is expected to allow this; if it now refuses, ALWAYS_ENFORCE "
            "has been made to escalate from off and this test should be inverted"
        )

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
