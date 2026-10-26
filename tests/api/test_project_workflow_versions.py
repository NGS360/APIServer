"""Tests for /projects/{project_id}/workflow-versions."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from api.platforms.models import Platform
from api.project.models import Project, ProjectWorkflowVersion
from api.workflow.models import (
    Workflow,
    WorkflowDeployment,
    WorkflowVersion,
    WorkflowVersionAlias,
)

ENGINE = "AWSHealthOmics (us-east)"
RESOLVE = {"engine": ENGINE, "alias": "prod"}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _url(project: Project, workflow_id: str, suffix: str = "") -> str:
    return f"/api/v1/projects/{project.project_id}/workflow-versions/{workflow_id}{suffix}"


def _record_url(project: Project, workflow_id: str) -> str:
    """DELETE addresses one record, so the engine is a required query parameter."""
    return f"{_url(project, workflow_id)}?engine={ENGINE}"


@pytest.fixture(name="workflow")
def workflow_fixture(session: Session) -> dict:
    """
    A workflow with versions 1-3, each deployed on Omics except version 3, and
    `prod` pointing at version 2.
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
    session.add(WorkflowVersionAlias(
        workflow_id=wf.id, alias="prod",
        workflow_version_id=versions[2].id, created_by="testuser",
    ))
    session.commit()
    return {"id": str(wf.id), "uuid": wf.id, "versions": versions}


def _move_prod(session: Session, workflow: dict, version: int) -> None:
    alias = session.exec(
        select(WorkflowVersionAlias).where(WorkflowVersionAlias.workflow_id == workflow["uuid"])
    ).one()
    alias.workflow_version_id = workflow["versions"][version].id
    session.commit()


# ---------------------------------------------------------------------------
# POST .../resolve
# ---------------------------------------------------------------------------

def test_first_resolve_records_prod(client: TestClient, test_project, workflow):
    resp = client.post(_url(test_project, workflow["id"], "/resolve"), json=RESOLVE)
    assert resp.status_code == 201
    data = resp.json()
    assert data["version"] == 2
    assert data["created"] is True
    assert data["external_id"].endswith("/version/2")
    assert data["created_by"] == "testuser"
    assert data["updated_at"] is None


def test_resolve_reuses_record_after_prod_moves(
    client: TestClient, session: Session, test_project, workflow,
):
    client.post(_url(test_project, workflow["id"], "/resolve"), json=RESOLVE)
    _move_prod(session, workflow, 1)

    resp = client.post(_url(test_project, workflow["id"], "/resolve"), json=RESOLVE)
    assert resp.status_code == 200
    assert resp.json()["version"] == 2
    assert resp.json()["created"] is False
    assert "already records version 2" in resp.json()["message"]


def test_resolve_with_explicit_version_records_it(client: TestClient, test_project, workflow):
    """No alias needed: the caller asks for version 1 directly."""
    resp = client.post(
        _url(test_project, workflow["id"], "/resolve"), json={"engine": ENGINE, "version": 1},
    )
    assert resp.status_code == 201
    assert resp.json()["version"] == 1


def test_resolve_explicit_version_matching_record_returns_it(
    client: TestClient, test_project, workflow,
):
    client.post(_url(test_project, workflow["id"], "/resolve"), json=RESOLVE)
    resp = client.post(
        _url(test_project, workflow["id"], "/resolve"), json={"engine": ENGINE, "version": 2},
    )
    assert resp.status_code == 200
    assert resp.json()["version"] == 2
    assert resp.json()["message"] is None


def test_resolve_existing_record_wins_over_requested_version(
    client: TestClient, test_project, workflow,
):
    """The recorded version is returned, with a message saying the request was not applied."""
    client.post(_url(test_project, workflow["id"], "/resolve"), json=RESOLVE)
    resp = client.post(
        _url(test_project, workflow["id"], "/resolve"), json={"engine": ENGINE, "version": 1},
    )
    assert resp.status_code == 200
    assert resp.json()["version"] == 2
    assert "already records version 2" in resp.json()["message"]


def test_resolve_explicit_undeployed_version_is_422(client: TestClient, test_project, workflow):
    resp = client.post(
        _url(test_project, workflow["id"], "/resolve"), json={"engine": ENGINE, "version": 3},
    )
    assert resp.status_code == 422


def test_resolve_explicit_unknown_version_is_404(client: TestClient, test_project, workflow):
    resp = client.post(
        _url(test_project, workflow["id"], "/resolve"), json={"engine": ENGINE, "version": 9},
    )
    assert resp.status_code == 404


def test_resolve_unset_alias_is_404(client: TestClient, test_project, workflow):
    resp = client.post(
        _url(test_project, workflow["id"], "/resolve"),
        json={"engine": ENGINE, "alias": "missing"},
    )
    assert resp.status_code == 404


def test_resolve_with_neither_only_reads(
    client: TestClient, session: Session, test_project, workflow,
):
    """Neither alias nor version: return the record if there is one, else 404 and write nothing."""
    url = _url(test_project, workflow["id"], "/resolve")
    resp = client.post(url, json={"engine": ENGINE})
    assert resp.status_code == 404
    assert session.exec(select(ProjectWorkflowVersion)).all() == []

    client.post(url, json=RESOLVE)
    resp = client.post(url, json={"engine": ENGINE})
    assert resp.status_code == 200
    assert resp.json()["version"] == 2
    assert resp.json()["message"] is None


def test_resolve_with_unmoved_alias_has_no_message(
    client: TestClient, test_project, workflow,
):
    """Nothing to report when the alias still points at the recorded version."""
    url = _url(test_project, workflow["id"], "/resolve")
    client.post(url, json=RESOLVE)
    resp = client.post(url, json=RESOLVE)
    assert resp.status_code == 200
    assert resp.json()["message"] is None


def test_resolve_rejects_both_alias_and_version(client: TestClient, test_project, workflow):
    resp = client.post(
        _url(test_project, workflow["id"], "/resolve"),
        json={"engine": ENGINE, "alias": "prod", "version": 1},
    )
    assert resp.status_code == 422


def test_resolve_undeployed_version_is_422_and_records_nothing(
    client: TestClient, session: Session, test_project, workflow,
):
    _move_prod(session, workflow, 3)
    resp = client.post(_url(test_project, workflow["id"], "/resolve"), json=RESOLVE)
    assert resp.status_code == 422
    assert session.exec(select(ProjectWorkflowVersion)).all() == []


def test_resolve_unknown_workflow_is_404(client: TestClient, test_project, workflow):
    resp = client.post(
        _url(test_project, "00000000-0000-0000-0000-000000000000", "/resolve"),
        json=RESOLVE,
    )
    assert resp.status_code == 404


def test_resolve_unknown_project_is_404(client: TestClient, workflow):
    resp = client.post(
        f"/api/v1/projects/P-00000000-0000/workflow-versions/{workflow['id']}/resolve",
        json=RESOLVE,
    )
    assert resp.status_code == 404


def test_duplicate_record_is_rejected(session: Session, test_project, workflow):
    """The unique constraint is what guarantees one version per project, workflow and engine."""
    for _ in range(2):
        session.add(ProjectWorkflowVersion(
            project_id=test_project.project_id, workflow_id=workflow["uuid"],
            version=1, engine=ENGINE, created_by="testuser",
        ))
    with pytest.raises(IntegrityError):
        session.commit()
    session.rollback()


# ---------------------------------------------------------------------------
# GET
# ---------------------------------------------------------------------------

def _list_url(project: Project, **filters) -> str:
    query = "&".join(f"{k}={v}" for k, v in filters.items())
    url = f"/api/v1/projects/{project.project_id}/workflow-versions"
    return f"{url}?{query}" if query else url


def test_list_and_filter(client: TestClient, test_project, workflow):
    client.post(_url(test_project, workflow["id"], "/resolve"), json=RESOLVE)

    for url in (
        _list_url(test_project),
        _list_url(test_project, workflow_id=workflow["id"]),
        _list_url(test_project, workflow_id=workflow["id"], engine=ENGINE),
    ):
        resp = client.get(url)
        assert resp.status_code == 200
        assert [r["version"] for r in resp.json()] == [2]

    other_engine = client.get(_list_url(test_project, engine="Arvados"))
    assert other_engine.json() == []


def test_list_without_records_is_empty(client: TestClient, test_project, workflow):
    resp = client.get(_list_url(test_project, workflow_id=workflow["id"]))
    assert resp.status_code == 200
    assert resp.json() == []


def test_list_with_unknown_workflow_is_404(client: TestClient, test_project, workflow):
    """A mistyped workflow id fails loudly instead of looking like 'nothing recorded'."""
    resp = client.get(
        _list_url(test_project, workflow_id="00000000-0000-0000-0000-000000000000")
    )
    assert resp.status_code == 404


def test_engine_is_required(client: TestClient, test_project, workflow):
    deleted = client.delete(_url(test_project, workflow["id"]))
    assert deleted.status_code == 422

    resolved = client.post(
        _url(test_project, workflow["id"], "/resolve"), json={"alias": "prod"},
    )
    assert resolved.status_code == 422


# ---------------------------------------------------------------------------
# PUT
# ---------------------------------------------------------------------------

def test_put_overwrites_existing_record(client: TestClient, test_project, workflow):
    client.post(_url(test_project, workflow["id"], "/resolve"), json=RESOLVE)

    resp = client.put(_url(test_project, workflow["id"]), json={"engine": ENGINE, "version": 1})
    assert resp.status_code == 200
    assert resp.json()["version"] == 1
    assert resp.json()["updated_by"] == "testuser"

    after = client.post(_url(test_project, workflow["id"], "/resolve"), json=RESOLVE)
    assert after.json()["version"] == 1


def test_put_creates_record_when_none_exists(client: TestClient, test_project, workflow):
    """A version chosen before anything is recorded is still marked as chosen."""
    resp = client.put(_url(test_project, workflow["id"]), json={"engine": ENGINE, "version": 1})
    assert resp.status_code == 200
    data = resp.json()
    assert data["version"] == 1
    assert data["created_by"] == "testuser"
    assert data["updated_at"] is not None


def test_put_undeployed_version_is_422(client: TestClient, test_project, workflow):
    resp = client.put(_url(test_project, workflow["id"]), json={"engine": ENGINE, "version": 3})
    assert resp.status_code == 422


def test_put_unknown_version_is_404(client: TestClient, test_project, workflow):
    resp = client.put(_url(test_project, workflow["id"]), json={"engine": ENGINE, "version": 9})
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# DELETE
# ---------------------------------------------------------------------------

def test_delete_then_resolve_records_current_prod(
    client: TestClient, session: Session, test_project, workflow,
):
    client.post(_url(test_project, workflow["id"], "/resolve"), json=RESOLVE)
    _move_prod(session, workflow, 1)

    deleted = client.delete(_record_url(test_project, workflow["id"]))
    assert deleted.status_code == 204

    resp = client.post(_url(test_project, workflow["id"], "/resolve"), json=RESOLVE)
    assert resp.status_code == 201
    assert resp.json()["version"] == 1


def test_delete_without_record_is_404(client: TestClient, test_project, workflow):
    resp = client.delete(_record_url(test_project, workflow["id"]))
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Permissions
# ---------------------------------------------------------------------------

def test_caller_without_project_roles_is_refused(
    restricted_client: TestClient, test_project, workflow,
):
    put = restricted_client.put(
        _url(test_project, workflow["id"]), json={"engine": ENGINE, "version": 1},
    )
    assert put.status_code == 403

    deleted = restricted_client.delete(_record_url(test_project, workflow["id"]))
    assert deleted.status_code == 403

    resolved = restricted_client.post(
        _url(test_project, workflow["id"], "/resolve"), json=RESOLVE,
    )
    assert resolved.status_code == 403
