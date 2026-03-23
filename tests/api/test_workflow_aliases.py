"""Tests for WorkflowVersionAlias CRUD endpoints."""

from fastapi.testclient import TestClient
from sqlmodel import Session

from api.workflow.models import Workflow, WorkflowVersion


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _create_workflow_and_version(
    session: Session,
    version: str = "1.0.0",
) -> tuple[str, str]:
    """Insert a workflow + version; return (wf_id, version_id)."""
    wf = Workflow(name="Alias Test WF", created_by="testuser")
    session.add(wf)
    session.flush()
    ver = WorkflowVersion(
        workflow_id=wf.id,
        version=version,
        definition_uri=f"s3://bucket/{version}.wdl",
        created_by="testuser",
    )
    session.add(ver)
    session.commit()
    session.refresh(wf)
    session.refresh(ver)
    return str(wf.id), str(ver.id)


# ---------------------------------------------------------------------------
# PUT /workflows/{id}/aliases/{alias}
# ---------------------------------------------------------------------------

def test_set_alias(client: TestClient, session: Session):
    """Set the production alias."""
    wf_id, ver_id = _create_workflow_and_version(session)

    body = {"workflow_version_id": ver_id}
    resp = client.put(
        f"/api/v1/workflows/{wf_id}/aliases/production",
        json=body,
    )
    assert resp.status_code == 200
    data = resp.json()

    assert data["alias"] == "production"
    assert data["workflow_version_id"] == ver_id
    assert data["version"] == "1.0.0"
    assert data["workflow_id"] == wf_id
    assert data["created_by"] == "testuser"


def test_set_alias_development(
    client: TestClient, session: Session,
):
    """Set the development alias."""
    wf_id, ver_id = _create_workflow_and_version(session)

    resp = client.put(
        f"/api/v1/workflows/{wf_id}/aliases/development",
        json={"workflow_version_id": ver_id},
    )
    assert resp.status_code == 200
    assert resp.json()["alias"] == "development"


def test_set_alias_invalid_value(
    client: TestClient, session: Session,
):
    """Invalid alias value is rejected by the enum."""
    wf_id, ver_id = _create_workflow_and_version(session)

    resp = client.put(
        f"/api/v1/workflows/{wf_id}/aliases/staging",
        json={"workflow_version_id": ver_id},
    )
    assert resp.status_code == 422


def test_move_alias_to_different_version(
    client: TestClient, session: Session,
):
    """Moving an alias to a new version works (upsert)."""
    wf = Workflow(name="Move Alias WF", created_by="testuser")
    session.add(wf)
    session.flush()
    v1 = WorkflowVersion(
        workflow_id=wf.id, version="1.0.0",
        definition_uri="s3://b/v1.wdl", created_by="testuser",
    )
    v2 = WorkflowVersion(
        workflow_id=wf.id, version="2.0.0",
        definition_uri="s3://b/v2.wdl", created_by="testuser",
    )
    session.add_all([v1, v2])
    session.commit()
    session.refresh(wf)
    session.refresh(v1)
    session.refresh(v2)

    wf_id = str(wf.id)
    v1_id = str(v1.id)
    v2_id = str(v2.id)

    # Set to v1
    resp1 = client.put(
        f"/api/v1/workflows/{wf_id}/aliases/production",
        json={"workflow_version_id": v1_id},
    )
    assert resp1.status_code == 200
    assert resp1.json()["version"] == "1.0.0"

    # Move to v2
    resp2 = client.put(
        f"/api/v1/workflows/{wf_id}/aliases/production",
        json={"workflow_version_id": v2_id},
    )
    assert resp2.status_code == 200
    assert resp2.json()["version"] == "2.0.0"


def test_set_alias_version_not_found(
    client: TestClient, session: Session,
):
    """Alias pointing to non-existent version returns 404."""
    wf = Workflow(name="No-Ver WF", created_by="testuser")
    session.add(wf)
    session.commit()
    session.refresh(wf)

    fake_ver = "00000000-0000-0000-0000-000000000000"
    resp = client.put(
        f"/api/v1/workflows/{wf.id}/aliases/production",
        json={"workflow_version_id": fake_ver},
    )
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# GET /workflows/{id}/aliases
# ---------------------------------------------------------------------------

def test_get_aliases_empty(
    client: TestClient, session: Session,
):
    """No aliases returns empty list."""
    wf = Workflow(name="Empty Aliases", created_by="testuser")
    session.add(wf)
    session.commit()
    session.refresh(wf)

    resp = client.get(
        f"/api/v1/workflows/{wf.id}/aliases",
    )
    assert resp.status_code == 200
    assert resp.json() == []


def test_get_aliases_multiple(
    client: TestClient, session: Session,
):
    """List aliases after setting both production and development."""
    wf_id, ver_id = _create_workflow_and_version(session)

    client.put(
        f"/api/v1/workflows/{wf_id}/aliases/production",
        json={"workflow_version_id": ver_id},
    )
    client.put(
        f"/api/v1/workflows/{wf_id}/aliases/development",
        json={"workflow_version_id": ver_id},
    )

    resp = client.get(
        f"/api/v1/workflows/{wf_id}/aliases",
    )
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 2
    alias_names = {a["alias"] for a in data}
    assert alias_names == {"production", "development"}


# ---------------------------------------------------------------------------
# DELETE /workflows/{id}/aliases/{alias}
# ---------------------------------------------------------------------------

def test_delete_alias(client: TestClient, session: Session):
    """Delete an alias returns 204."""
    wf_id, ver_id = _create_workflow_and_version(session)

    client.put(
        f"/api/v1/workflows/{wf_id}/aliases/production",
        json={"workflow_version_id": ver_id},
    )

    del_resp = client.delete(
        f"/api/v1/workflows/{wf_id}/aliases/production",
    )
    assert del_resp.status_code == 204

    # Verify it's gone
    list_resp = client.get(
        f"/api/v1/workflows/{wf_id}/aliases",
    )
    assert list_resp.json() == []


def test_delete_alias_not_found(
    client: TestClient, session: Session,
):
    """Deleting a non-existent alias returns 404."""
    wf = Workflow(name="No Alias", created_by="testuser")
    session.add(wf)
    session.commit()
    session.refresh(wf)

    resp = client.delete(
        f"/api/v1/workflows/{wf.id}/aliases/production",
    )
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Workflow GET includes aliases
# ---------------------------------------------------------------------------

def test_workflow_public_includes_aliases(
    client: TestClient, session: Session,
):
    """GET /workflows/{id} includes nested alias data."""
    wf_id, ver_id = _create_workflow_and_version(session)

    client.put(
        f"/api/v1/workflows/{wf_id}/aliases/production",
        json={"workflow_version_id": ver_id},
    )

    resp = client.get(f"/api/v1/workflows/{wf_id}")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["aliases"]) == 1
    assert data["aliases"][0]["alias"] == "production"
    assert data["aliases"][0]["version"] == "1.0.0"
