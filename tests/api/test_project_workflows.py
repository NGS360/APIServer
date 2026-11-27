"""
POST /projects/{project_id}/workflows and POST /projects/{project_id}/workflows/copy.

Both are guarded on workflow:create in the project plane. The copy also needs
project:read on its source project, checked in the handler.

RBAC_MODE is `enforce` in tests unless a test overrides it, so refusals are 403s.
"""
import gzip
import uuid

import pytest
from sqlmodel import select

from api.auth.models import User
from api.project.models import (
    Project,
    ProjectWorkflow,
    WorkflowAttribute,
    WorkflowVersion,
    WorkflowVersionAlias,
    WorkflowVersionAttribute,
)
from api.rbac.models import GrantSource, ProjectMember, Role
from api.rbac.permissions import Permission
from api.rbac.roles import ROLE_DEFINITIONS

CREATE_URL = "/api/v1/projects/{project_id}/workflows"
COPY_URL = "/api/v1/projects/{project_id}/workflows/copy"


def make_project(session, suffix: str) -> Project:
    project = Project(
        project_id=f"P-20260201-{suffix}",
        name=f"Project {suffix}",
        created_by="someone-else",
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


def make_workflow_with_history(session, project: Project, name: str) -> ProjectWorkflow:
    """A workflow with attributes, two versions (one with attributes), and two aliases."""
    workflow = ProjectWorkflow(project_id=project.project_id, name=name, created_by="author")
    session.add(workflow)
    session.commit()
    session.refresh(workflow)

    session.add(WorkflowAttribute(workflow_id=workflow.id, key="pipeline", value="rnaseq"))

    v1 = WorkflowVersion(
        workflow_id=workflow.id, version=1,
        definition_uri="s3://example/v1.wdl",
        body=gzip.compress(b"workflow v1 {}"),
        inputs=[{"name": "fastq"}], outputs=[{"name": "bam"}],
        created_by="author",
    )
    v2 = WorkflowVersion(
        workflow_id=workflow.id, version=2,
        definition_uri="s3://example/v2.wdl",
        body=gzip.compress(b"workflow v2 {}"),
        created_by="author",
    )
    session.add_all([v1, v2])
    session.commit()
    session.refresh(v1)
    session.refresh(v2)

    session.add(WorkflowVersionAttribute(
        workflowversion_id=v2.id, key="container", value="img:2",
    ))
    session.add(WorkflowVersionAlias(
        workflow_id=workflow.id, workflow_version_id=v1.id,
        alias="production", created_by="author",
    ))
    session.add(WorkflowVersionAlias(
        workflow_id=workflow.id, workflow_version_id=v2.id,
        alias="development", created_by="author",
    ))
    session.commit()
    session.refresh(workflow)
    return workflow


@pytest.fixture(name="contributor_client")
def contributor_client_fixture(client_with_permissions):
    """Holds no global permissions; gets workflow:create only through a project role."""
    return client_with_permissions(frozenset(), username="contrib")


@pytest.fixture(name="viewer_client")
def viewer_client_fixture(client_with_permissions):
    return client_with_permissions(frozenset(), username="viewer")


class TestCreate:

    def test_a_project_contributor_creates_a_workflow(self, session, contributor_client):
        project = make_project(session, "C001")
        grant_project_role(session, project, "contrib", "project_contributor")

        response = contributor_client.post(
            CREATE_URL.format(project_id=project.project_id),
            json={"name": "germline", "body": "workflow text"},
        )

        assert response.status_code == 201, response.text
        body = response.json()
        assert body["name"] == "germline"
        assert body["project_id"] == project.project_id
        assert body["created_by"] == "contrib"

        workflow = session.exec(
            select(ProjectWorkflow).where(ProjectWorkflow.name == "germline")
        ).one()
        version = session.exec(
            select(WorkflowVersion).where(WorkflowVersion.workflow_id == workflow.id)
        ).one()
        assert version.version == 1
        assert version.definition_uri == ""
        assert version.created_by == "contrib"
        assert gzip.decompress(version.body) == b"workflow text"

    def test_attributes_and_version_attributes_are_stored(self, session, contributor_client):
        project = make_project(session, "C005")
        grant_project_role(session, project, "contrib", "project_contributor")

        response = contributor_client.post(
            CREATE_URL.format(project_id=project.project_id),
            json={
                "name": "attrs",
                "body": "workflow text",
                "attributes": [{"key": "owner", "value": "lab"}],
                "version_attributes": [{"key": "tool", "value": "gatk"}],
            },
        )

        assert response.status_code == 201, response.text
        workflow = session.exec(
            select(ProjectWorkflow).where(ProjectWorkflow.name == "attrs")
        ).one()
        attrs = session.exec(
            select(WorkflowAttribute).where(WorkflowAttribute.workflow_id == workflow.id)
        ).all()
        assert [(a.key, a.value) for a in attrs] == [("owner", "lab")]
        version = session.exec(
            select(WorkflowVersion).where(WorkflowVersion.workflow_id == workflow.id)
        ).one()
        version_attrs = session.exec(
            select(WorkflowVersionAttribute).where(
                WorkflowVersionAttribute.workflowversion_id == version.id
            )
        ).all()
        assert [(a.key, a.value) for a in version_attrs] == [("tool", "gatk")]

    def test_duplicate_attribute_keys_are_rejected_and_nothing_is_created(
        self, session, contributor_client,
    ):
        project = make_project(session, "C006")
        grant_project_role(session, project, "contrib", "project_contributor")

        response = contributor_client.post(
            CREATE_URL.format(project_id=project.project_id),
            json={
                "name": "dupes",
                "body": "workflow text",
                "attributes": [{"key": "owner", "value": "a"}, {"key": "Owner", "value": "b"}],
            },
        )

        assert response.status_code == 400, response.text
        assert session.exec(
            select(ProjectWorkflow).where(ProjectWorkflow.name == "dupes")
        ).first() is None

    def test_a_zip_definition_uri_is_unpacked_and_stored_as_gzip(
        self, session, contributor_client, tmp_path,
    ):
        import io
        import zipfile

        project = make_project(session, "C007")
        grant_project_role(session, project, "contrib", "project_contributor")
        archive = tmp_path / "wf.zip"
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("main.wdl", "workflow zipped {}")
        archive.write_bytes(buf.getvalue())

        response = contributor_client.post(
            CREATE_URL.format(project_id=project.project_id),
            json={"name": "zipped", "definition_uri": str(archive)},
        )

        assert response.status_code == 201, response.text
        workflow = session.exec(
            select(ProjectWorkflow).where(ProjectWorkflow.name == "zipped")
        ).one()
        version = session.exec(
            select(WorkflowVersion).where(WorkflowVersion.workflow_id == workflow.id)
        ).one()
        assert gzip.decompress(version.body) == b"workflow zipped {}"

    def test_a_gzip_definition_uri_is_stored_without_recompressing(
        self, session, contributor_client, tmp_path,
    ):
        project = make_project(session, "C008")
        grant_project_role(session, project, "contrib", "project_contributor")
        path = tmp_path / "wf.wdl.gz"
        path.write_bytes(gzip.compress(b"workflow gzipped {}"))

        response = contributor_client.post(
            CREATE_URL.format(project_id=project.project_id),
            json={"name": "gzipped", "definition_uri": str(path)},
        )

        assert response.status_code == 201, response.text
        workflow = session.exec(
            select(ProjectWorkflow).where(ProjectWorkflow.name == "gzipped")
        ).one()
        version = session.exec(
            select(WorkflowVersion).where(WorkflowVersion.workflow_id == workflow.id)
        ).one()
        assert gzip.decompress(version.body) == b"workflow gzipped {}"

    def test_a_missing_body_is_rejected_and_nothing_is_created(self, session, contributor_client):
        project = make_project(session, "C003")
        grant_project_role(session, project, "contrib", "project_contributor")

        response = contributor_client.post(
            CREATE_URL.format(project_id=project.project_id),
            json={"name": "empty"},
        )

        assert response.status_code == 400, response.text
        assert session.exec(
            select(ProjectWorkflow).where(ProjectWorkflow.name == "empty")
        ).first() is None

    def test_body_and_definition_uri_together_are_rejected(self, session, contributor_client):
        project = make_project(session, "C004")
        grant_project_role(session, project, "contrib", "project_contributor")

        response = contributor_client.post(
            CREATE_URL.format(project_id=project.project_id),
            json={"name": "both", "body": "text", "definition_uri": "s3://x/y.wdl"},
        )

        assert response.status_code == 422, response.text

    def test_a_viewer_is_refused(self, session, viewer_client):
        project = make_project(session, "C002")
        grant_project_role(session, project, "viewer", "project_viewer")

        response = viewer_client.post(
            CREATE_URL.format(project_id=project.project_id),
            json={"name": "germline"},
        )

        assert response.status_code == 403
        assert session.exec(
            select(ProjectWorkflow).where(ProjectWorkflow.project_id == project.project_id)
        ).first() is None

    def test_a_duplicate_name_in_the_project_is_a_conflict(
        self, session, contributor_client
    ):
        project = make_project(session, "C003")
        grant_project_role(session, project, "contrib", "project_contributor")
        url = CREATE_URL.format(project_id=project.project_id)

        payload = {"name": "germline", "body": "workflow text"}
        assert contributor_client.post(url, json=payload).status_code == 201
        response = contributor_client.post(url, json=payload)

        assert response.status_code == 409

    def test_an_empty_name_is_rejected(self, session, contributor_client):
        project = make_project(session, "C004")
        grant_project_role(session, project, "contrib", "project_contributor")

        response = contributor_client.post(
            CREATE_URL.format(project_id=project.project_id), json={"name": ""},
        )

        assert response.status_code == 422


class TestCopy:

    def test_a_copy_carries_attributes_versions_bodies_and_aliases(
        self, session, contributor_client
    ):
        source_project = make_project(session, "K001")
        target_project = make_project(session, "K002")
        grant_project_role(session, target_project, "contrib", "project_contributor")
        grant_project_role(session, source_project, "contrib", "project_viewer")
        source = make_workflow_with_history(session, source_project, "germline")

        response = contributor_client.post(
            COPY_URL.format(project_id=target_project.project_id),
            json={"source_workflow_id": str(source.id)},
        )

        assert response.status_code == 201, response.text
        copy_id = uuid.UUID(response.json()["id"])
        assert copy_id != source.id
        copy = session.get(ProjectWorkflow, copy_id)
        assert copy.project_id == target_project.project_id
        assert copy.name == "germline"
        assert copy.created_by == "contrib"

        assert [(a.key, a.value) for a in copy.attributes] == [("pipeline", "rnaseq")]

        versions = sorted(copy.versions, key=lambda v: v.version)
        assert [v.version for v in versions] == [1, 2]
        assert [gzip.decompress(v.body) for v in versions] == [
            b"workflow v1 {}", b"workflow v2 {}",
        ]
        assert [v.definition_uri for v in versions] == [
            "s3://example/v1.wdl", "s3://example/v2.wdl",
        ]
        assert versions[0].inputs == [{"name": "fastq"}]
        assert versions[0].outputs == [{"name": "bam"}]
        assert [(a.key, a.value) for a in versions[1].attributes] == [("container", "img:2")]
        assert all(v.created_by == "contrib" for v in versions)
        assert all(v.id not in {sv.id for sv in source.versions} for v in versions)

        aliases = {a.alias: a.workflow_version_id for a in copy.aliases}
        assert aliases == {"production": versions[0].id, "development": versions[1].id}

        # The source is untouched.
        session.refresh(source)
        assert len(source.versions) == 2
        assert {a.workflow_version_id for a in source.aliases} == {
            sv.id for sv in source.versions
        }

    def test_the_copy_can_be_given_a_new_name(self, session, contributor_client):
        source_project = make_project(session, "K003")
        target_project = make_project(session, "K004")
        grant_project_role(session, target_project, "contrib", "project_contributor")
        grant_project_role(session, source_project, "contrib", "project_viewer")
        source = make_workflow_with_history(session, source_project, "germline")

        response = contributor_client.post(
            COPY_URL.format(project_id=target_project.project_id),
            json={"source_workflow_id": str(source.id), "name": "germline-v2"},
        )

        assert response.status_code == 201
        assert response.json()["name"] == "germline-v2"

    def test_copying_into_a_project_that_already_has_the_name_is_a_conflict(
        self, session, contributor_client
    ):
        source_project = make_project(session, "K005")
        target_project = make_project(session, "K006")
        grant_project_role(session, target_project, "contrib", "project_contributor")
        grant_project_role(session, source_project, "contrib", "project_viewer")
        source = make_workflow_with_history(session, source_project, "germline")
        make_workflow_with_history(session, target_project, "germline")

        response = contributor_client.post(
            COPY_URL.format(project_id=target_project.project_id),
            json={"source_workflow_id": str(source.id)},
        )

        assert response.status_code == 409

    def test_a_missing_source_is_not_found(self, session, contributor_client):
        target_project = make_project(session, "K007")
        grant_project_role(session, target_project, "contrib", "project_contributor")

        response = contributor_client.post(
            COPY_URL.format(project_id=target_project.project_id),
            json={"source_workflow_id": str(uuid.uuid4())},
        )

        assert response.status_code == 404

    def test_a_viewer_of_the_target_cannot_copy_into_it(self, session, viewer_client):
        source_project = make_project(session, "K008")
        target_project = make_project(session, "K009")
        grant_project_role(session, target_project, "viewer", "project_viewer")
        source = make_workflow_with_history(session, source_project, "germline")

        response = viewer_client.post(
            COPY_URL.format(project_id=target_project.project_id),
            json={"source_workflow_id": str(source.id)},
        )

        assert response.status_code == 403

    def test_a_caller_who_cannot_read_the_source_project_is_refused(
        self, session, client_with_permissions
    ):
        """
        Holds workflow:create globally, so the target check passes everywhere, but
        no project:read anywhere. Without the source check this would copy a
        workflow out of a project the caller could not view.
        """
        source_project = make_project(session, "K010")
        target_project = make_project(session, "K011")
        source = make_workflow_with_history(session, source_project, "germline")
        client = client_with_permissions(
            frozenset({Permission.WORKFLOW_CREATE}), username="writer-only",
        )

        response = client.post(
            COPY_URL.format(project_id=target_project.project_id),
            json={"source_workflow_id": str(source.id)},
        )

        assert response.status_code == 403
        assert session.exec(
            select(ProjectWorkflow).where(
                ProjectWorkflow.project_id == target_project.project_id
            )
        ).first() is None


class TestCopyLineage:

    def test_a_copy_records_its_immediate_source(self, session, contributor_client):
        source_project = make_project(session, "L001")
        target_project = make_project(session, "L002")
        grant_project_role(session, source_project, "contrib", "project_viewer")
        grant_project_role(session, target_project, "contrib", "project_contributor")
        source = make_workflow_with_history(session, source_project, "germline")

        response = contributor_client.post(
            COPY_URL.format(project_id=target_project.project_id),
            json={"source_workflow_id": str(source.id)},
        )

        assert response.status_code == 201, response.text
        assert response.json()["copied_from_workflow_id"] == str(source.id)

    def test_a_copy_of_a_copy_points_at_the_intermediate_copy(
        self, session, contributor_client
    ):
        source_project = make_project(session, "L003")
        middle_project = make_project(session, "L004")
        final_project = make_project(session, "L005")
        grant_project_role(session, source_project, "contrib", "project_viewer")
        grant_project_role(session, middle_project, "contrib", "project_contributor")
        grant_project_role(session, final_project, "contrib", "project_contributor")
        source = make_workflow_with_history(session, source_project, "germline")

        first = contributor_client.post(
            COPY_URL.format(project_id=middle_project.project_id),
            json={"source_workflow_id": str(source.id)},
        ).json()
        second = contributor_client.post(
            COPY_URL.format(project_id=final_project.project_id),
            json={"source_workflow_id": first["id"]},
        )

        assert second.status_code == 201, second.text
        assert second.json()["copied_from_workflow_id"] == first["id"]

    def test_a_created_workflow_has_no_source(self, session, contributor_client):
        project = make_project(session, "L006")
        grant_project_role(session, project, "contrib", "project_contributor")

        response = contributor_client.post(
            CREATE_URL.format(project_id=project.project_id),
            json={"name": "fresh", "body": "workflow text"},
        )

        assert response.status_code == 201
        assert response.json()["copied_from_workflow_id"] is None


class TestRoleGrant:

    def test_contributor_holds_workflow_create_and_viewer_does_not(self):
        assert Permission.WORKFLOW_CREATE in ROLE_DEFINITIONS["project_contributor"].permissions
        assert Permission.WORKFLOW_CREATE not in ROLE_DEFINITIONS["project_viewer"].permissions


VERSIONS_URL = "/api/v1/projects/{project_id}/workflows/{workflow_id}/versions"


class TestCreateVersion:

    def create_workflow(self, client, project) -> uuid.UUID:
        response = client.post(
            CREATE_URL.format(project_id=project.project_id),
            json={"name": "germline", "body": "v1 text"},
        )
        assert response.status_code == 201, response.text
        return uuid.UUID(response.json()["id"])

    def test_a_new_version_gets_the_next_number(self, session, contributor_client):
        project = make_project(session, "V001")
        grant_project_role(session, project, "contrib", "project_contributor")
        workflow_id = self.create_workflow(contributor_client, project)
        url = VERSIONS_URL.format(project_id=project.project_id, workflow_id=workflow_id)

        first = contributor_client.post(url, json={"body": "v2 text"})
        second = contributor_client.post(url, json={
            "body": "v3 text",
            "version_attributes": [{"key": "tool", "value": "gatk"}],
        })

        assert first.status_code == 201, first.text
        assert first.json()["version"] == 2
        assert second.status_code == 201, second.text
        assert second.json()["version"] == 3
        assert "body" not in second.json()

        stored = session.exec(
            select(WorkflowVersion).where(
                WorkflowVersion.workflow_id == workflow_id, WorkflowVersion.version == 3,
            )
        ).one()
        assert gzip.decompress(stored.body) == b"v3 text"
        attrs = session.exec(
            select(WorkflowVersionAttribute).where(
                WorkflowVersionAttribute.workflowversion_id == stored.id
            )
        ).all()
        assert [(a.key, a.value) for a in attrs] == [("tool", "gatk")]

    def test_a_workflow_in_another_project_is_not_found(self, session, contributor_client):
        source = make_project(session, "V002")
        target = make_project(session, "V003")
        grant_project_role(session, source, "contrib", "project_contributor")
        grant_project_role(session, target, "contrib", "project_contributor")
        workflow_id = self.create_workflow(contributor_client, source)

        response = contributor_client.post(
            VERSIONS_URL.format(project_id=target.project_id, workflow_id=workflow_id),
            json={"body": "v2 text"},
        )

        assert response.status_code == 404, response.text

    def test_a_viewer_is_refused(self, session, viewer_client):
        project = make_project(session, "V004")
        grant_project_role(session, project, "viewer", "project_viewer")
        # Created directly: the test client acts as the viewer, so a contributor
        # request can't be made in the same test.
        workflow = ProjectWorkflow(project_id=project.project_id, name="germline", created_by="contrib")
        session.add(workflow)
        session.commit()
        session.refresh(workflow)
        workflow_id = workflow.id

        response = viewer_client.post(
            VERSIONS_URL.format(project_id=project.project_id, workflow_id=workflow_id),
            json={"body": "v2 text"},
        )

        assert response.status_code == 403, response.text

    def test_a_missing_body_adds_no_version(self, session, contributor_client):
        project = make_project(session, "V005")
        grant_project_role(session, project, "contrib", "project_contributor")
        workflow_id = self.create_workflow(contributor_client, project)

        response = contributor_client.post(
            VERSIONS_URL.format(project_id=project.project_id, workflow_id=workflow_id),
            json={},
        )

        assert response.status_code == 400, response.text
        versions = session.exec(
            select(WorkflowVersion).where(WorkflowVersion.workflow_id == workflow_id)
        ).all()
        assert [v.version for v in versions] == [1]
