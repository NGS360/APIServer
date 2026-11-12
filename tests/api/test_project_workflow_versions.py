"""Tests for /projects/{project_id}/workflow."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from api.platforms.models import Platform
from api.project.models import Project, ProjectWorkflowVersion
from api.workflow.models import Workflow, WorkflowDeployment, WorkflowVersion

ENGINE = "AWSHealthOmics (us-east)"
UNKNOWN_UUID = "00000000-0000-0000-0000-000000000000"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _url(project: Project, workflow_id: str) -> str:
    return f"/api/v1/projects/{project.project_id}/workflow/{workflow_id}"


def _list_url(project: Project, **filters) -> str:
    query = "&".join(f"{k}={v}" for k, v in filters.items())
    url = f"/api/v1/projects/{project.project_id}/workflow"
    return f"{url}?{query}" if query else url


@pytest.fixture(name="workflow")
def workflow_fixture(session: Session) -> dict:
    """
    A workflow with versions 1-3.

    Only versions 1 and 2 are deployed; version 3 is deliberately deployed
    nowhere, so a test can show that a version is recordable whether or not any
    platform can currently run it. No alias is set: aliases are a workflow-level
    concept and nothing in this API reads them.
    """
    session.add(Platform(name=ENGINE))
    wf = Workflow(name="Alignment", created_by="testuser")
    session.add(wf)
    session.flush()
    versions = {}
    for n in (1, 2, 3):
        ver = WorkflowVersion(
            workflow_id=wf.id, version=n,
            definition_uri=f"s3://bucket/v{n}.cwl", created_by="testuser",
        )
        session.add(ver)
        session.flush()
        versions[n] = ver
        if n < 3:
            session.add(WorkflowDeployment(
                workflow_version_id=ver.id, engine=ENGINE,
                external_id=f"arn:aws:omics:us-east-1:1:workflow/123/version/{n}",
                created_by="testuser",
            ))
    session.commit()
    return {"id": str(wf.id), "uuid": wf.id, "versions": versions}


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_put_records_then_overwrites(
    client: TestClient, session: Session, test_project, workflow,
):
    """
    PUT is the only writer, and the same call creates or replaces. The
    updated_* pair is what separates the two: unset on a create, so NULL means
    the record still holds the version it was first given.
    """
    created = client.put(_url(test_project, workflow["id"]), json={"version": 1})
    assert created.status_code == 200
    data = created.json()
    assert data["version"] == 1
    assert data["created_by"] == "testuser"
    assert data["updated_at"] is None
    assert data["updated_by"] is None
    # A version is all this records. Nothing platform-specific is returned:
    # which engines can run it is answered at submission time.
    assert "engine" not in data
    assert "external_id" not in data

    changed = client.put(_url(test_project, workflow["id"]), json={"version": 2})
    assert changed.status_code == 200
    assert changed.json()["version"] == 2
    assert changed.json()["updated_at"] is not None
    assert changed.json()["updated_by"] == "testuser"

    # Replaced, not added: one version per project and workflow.
    assert len(session.exec(select(ProjectWorkflowVersion)).all()) == 1


def test_put_accepts_a_version_deployed_nowhere(client: TestClient, test_project, workflow):
    """
    Version 3 has no deployment on any platform, and is still recorded.
    Deployment is a submission-time concern: refusing here would make the
    recorded version depend on which platform happened to ask first.
    """
    resp = client.put(_url(test_project, workflow["id"]), json={"version": 3})

    assert resp.status_code == 200
    assert resp.json()["version"] == 3


def test_record_is_listable_then_removable(client: TestClient, test_project, workflow):
    """
    The listing answers `[]` rather than 404 when nothing is recorded, which is
    what lets a caller tell "nothing recorded yet" from "no such project or
    workflow" -- the distinction PAML's copy_workflow depends on.
    """
    before = client.get(_list_url(test_project, workflow_id=workflow["id"]))
    assert before.json() == []

    client.put(_url(test_project, workflow["id"]), json={"version": 2})

    for url in (
        _list_url(test_project),
        _list_url(test_project, workflow_id=workflow["id"]),
    ):
        resp = client.get(url)
        assert resp.status_code == 200
        assert [r["version"] for r in resp.json()] == [2]

    deleted = client.delete(_url(test_project, workflow["id"]))
    assert deleted.status_code == 204

    after = client.get(_list_url(test_project, workflow_id=workflow["id"]))
    assert after.json() == []


def test_unknown_or_missing_is_404(client: TestClient, test_project, workflow):
    """
    A mistyped id fails loudly rather than recording the wrong thing or looking
    like "nothing recorded".
    """
    # Nothing recorded yet, so there is nothing to delete.
    deleted = client.delete(_url(test_project, workflow["id"]))
    assert deleted.status_code == 404

    # A workflow that does not exist, which must not read as an empty listing.
    listed = client.get(_list_url(test_project, workflow_id=UNKNOWN_UUID))
    assert listed.status_code == 404

    for url, version in (
        (_url(test_project, workflow["id"]), 9),                              # no version
        (_url(test_project, UNKNOWN_UUID), 1),                                # no workflow
        (f"/api/v1/projects/P-00000000-0000/workflow/{workflow['id']}", 1),   # no project
    ):
        written = client.put(url, json={"version": version})
        assert written.status_code == 404, url


def test_duplicate_record_is_rejected(session: Session, test_project, workflow):
    """
    The unique constraint is what guarantees one version per project and
    workflow, whatever writes the rows -- not only the API. Note the two rows
    differ in version: the key is the project and workflow, so a second version
    of the same workflow is refused rather than stored alongside the first.
    """
    for version in (1, 2):
        session.add(ProjectWorkflowVersion(
            project_id=test_project.project_id, workflow_id=workflow["uuid"],
            version=version, created_by="testuser",
        ))
    with pytest.raises(IntegrityError):
        session.commit()
    session.rollback()
