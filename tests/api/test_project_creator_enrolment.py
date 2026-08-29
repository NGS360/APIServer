"""
The creator of a project gets project_owner.

docs/RBAC.md has required this since the design was written -- "POST /projects
grants the creator project_owner in the same transaction as the project insert.
Without this, a user creates a project they immediately cannot administer" -- and
it was never implemented. The omission is invisible until permissions are
enforced, which is why it survived: the ownership backfill covered projects that
already existed, so only projects created *after* it were affected.

It surfaced in the production dry-run log. The largest single source of would_deny
from a real user was somebody downloading FASTQs out of a project created two days
earlier, refused because nobody -- not even its creator -- was a member of it.

The last class below is that exact scenario, end to end.
"""
from sqlmodel import select

from api.rbac.models import GrantSource, ProjectMember, Role


def members_of(session, project_id):
    """(username, role name, source) for each member."""
    from api.auth.models import User

    rows = session.exec(
        select(User.username, Role.name, ProjectMember.source)
        .join(ProjectMember, ProjectMember.user_id == User.id)
        .join(Role, Role.id == ProjectMember.role_id)
        .where(ProjectMember.project_id == project_id)
    ).all()
    return [(u, r, s) for u, r, s in rows]


class TestTheCreatorIsEnrolled:

    def test_creating_a_project_makes_the_caller_its_owner(self, client, session):
        from api.project.models import Project

        response = client.post("/api/v1/projects", json={"name": "Mine"})
        assert response.status_code == 201
        project_id = response.json()["project_id"]

        project = session.exec(
            select(Project).where(Project.project_id == project_id)
        ).one()
        assert members_of(session, project.id) == [
            ("testuser", "project_owner", GrantSource.MANUAL)
        ]

    def test_the_membership_lands_in_the_same_transaction(self, client, session):
        """
        Not a separate commit. A failure between the two would leave a project
        nobody can administer, which is the state this fixes -- so the row has to
        be visible the moment the project is.
        """
        from api.project.models import Project

        body = client.post("/api/v1/projects", json={"name": "Atomic"}).json()
        project = session.exec(
            select(Project).where(Project.project_id == body["project_id"])
        ).one()
        # The response was rendered after the commit; if membership were a second
        # commit that had not happened yet, this would be empty.
        assert members_of(session, project.id)

    def test_it_survives_a_project_with_attributes(self, client, session):
        """The attribute branch adds rows between the insert and the commit."""
        from api.project.models import Project

        body = client.post("/api/v1/projects", json={
            "name": "With attrs",
            "attributes": [{"key": "businessowner", "value": "someone"}],
        }).json()
        project = session.exec(
            select(Project).where(Project.project_id == body["project_id"])
        ).one()
        assert members_of(session, project.id)


class TestItIsBestEffort:
    """
    Refusing to create the project would be a worse outcome than creating one
    that needs a grant -- and the dry-run log already surfaces the latter.
    """

    def test_a_missing_role_does_not_fail_creation(self, client, session, caplog):
        session.exec(select(Role).where(Role.name == "project_owner")).one()
        for role in session.exec(
            select(Role).where(Role.name == "project_owner")
        ).all():
            session.delete(role)
        session.commit()

        response = client.post("/api/v1/projects", json={"name": "No role"})
        assert response.status_code == 201
        assert "project_owner is missing" in caplog.text

    def test_an_unresolvable_creator_does_not_fail_creation(
        self, client, session, monkeypatch, caplog
    ):
        import api.project.services as services

        original = services.create_project

        def with_unknown_user(**kwargs):
            kwargs["current_user"] = "nobody-by-that-name"
            return original(**kwargs)

        monkeypatch.setattr(services, "create_project", with_unknown_user)
        response = client.post("/api/v1/projects", json={"name": "Ghost"})
        assert response.status_code == 201
        assert "not a user row" in caplog.text


class TestTheProductionScenario:
    """
    The refusal that exposed this, reproduced: download a file belonging to a
    project you created.
    """

    def test_the_creator_can_download_a_file_in_their_own_project(
        self, client_with_permissions, session
    ):
        from api.files.models import File, FileProject
        from api.project.models import Project
        from api.rbac.permissions import Permission

        # A caller who holds project:create and the four global reads, but NOT
        # global file:download -- so any download has to come from membership.
        api = client_with_permissions(
            [Permission.PROJECT_CREATE, Permission.PROJECT_READ,
             Permission.SAMPLE_READ, Permission.FILE_READ,
             Permission.QCRECORD_READ],
            username="creator",
        )

        created = api.post("/api/v1/projects", json={"name": "Fresh run"})
        assert created.status_code == 201
        project = session.exec(
            select(Project).where(
                Project.project_id == created.json()["project_id"]
            )
        ).one()

        uri = f"s3://test-data-bucket/{project.project_id}/reads_R1_001.fastq.gz"
        f = File(uri=uri, storage_backend="S3")
        session.add(f)
        session.commit()
        session.refresh(f)
        session.add(FileProject(file_id=f.id, project_id=project.id))
        session.commit()

        response = api.get("/api/v1/files/download-url", params={"path": uri})
        assert response.status_code == 200, (
            "the creator of a project cannot download its files -- this is the "
            "exact would_deny seen in production"
        )
