""" Test cases for the permission guards now attached to routes """


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


class TestTheAccessControlSurfaceIsGuarded:
    """
    The administrative surface is gated by its permission, and by nothing else.

    These routes used to carry CurrentSuperuser on top of their guard. It came
    off because it made the panel unusable by the very roles it administers --
    see TestTheAdminPanelWorksWithoutSuperuser below -- which leaves the
    permission as the only gate. These tests are the other half of that trade:
    the `client` fixture holds the pre-RBAC permission set, and must still be
    refused everywhere.
    """

    def test_settings_update_refuses_a_non_holder(self, client):
        r = client.put("/api/v1/settings/DATA_BUCKET_URI",
                       json={"value": "s3://hijacked"})
        assert r.status_code == 403

    def test_membership_read_refuses_a_non_holder(self, client, test_project):
        assert client.get(
            f"/api/v1/projects/{test_project.project_id}/members"
        ).status_code == 403

    def test_the_roster_refuses_a_non_holder(self, client):
        assert client.get("/api/v1/rbac/users").status_code == 403

    def test_user_flags_refuse_a_non_holder(self, client):
        assert client.patch(
            "/api/v1/users/testuser", json={"is_verified": True}
        ).status_code == 403

    def test_a_superuser_still_passes(self, superuser_client, test_project):
        assert superuser_client.get(
            f"/api/v1/projects/{test_project.project_id}/members"
        ).status_code == 200


class TestTheAdminPanelWorksWithoutSuperuser:
    """
    The point of removing CurrentSuperuser: a role that carries the permission
    is now sufficient.

    Before this, an `auditor` -- read-only across the platform, and the role
    compliance actually uses -- held role:read and was still refused by every
    route it names, because the dependency ran first.
    """

    def test_an_auditor_can_read_the_catalog(self, auditor_client):
        assert auditor_client.get("/api/v1/rbac/permissions").status_code == 200

    def test_an_auditor_can_read_the_roster(self, auditor_client):
        assert auditor_client.get("/api/v1/rbac/users").status_code == 200

    def test_an_auditor_can_read_roles(self, auditor_client):
        assert auditor_client.get("/api/v1/rbac/roles").status_code == 200

    def test_an_auditor_cannot_grant(self, auditor_client):
        """role:read is not role:manage, and the mutations are still refused."""
        r = auditor_client.post("/api/v1/rbac/users/testuser/roles",
                                json={"role": "lab_manager"})
        assert r.status_code == 403

    def test_a_project_owner_can_read_its_membership(
        self, project_owner_client, test_project
    ):
        """
        The self-serve case the project plane exists for: an owner who is not a
        superuser and holds no global administrative role.
        """
        r = project_owner_client.get(
            f"/api/v1/projects/{test_project.project_id}/members"
        )
        assert r.status_code == 200

    def test_a_project_owner_cannot_read_another_project(
        self, project_owner_client, other_project
    ):
        """The grant is per project, so it must not generalise."""
        assert project_owner_client.get(
            f"/api/v1/projects/{other_project.project_id}/members"
        ).status_code == 403


class TestSelfServiceIsUnguarded:

    def test_rbac_me_needs_no_permission(self, restricted_client):
        """A user with no roles must still be able to discover that."""
        r = restricted_client.get("/api/v1/rbac/me")
        assert r.status_code == 200
        assert r.json()["global_permissions"] == []
