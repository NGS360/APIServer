"""Tests for WorkflowVersionAlias CRUD endpoints."""

from fastapi.testclient import TestClient
from sqlmodel import Session

from api.workflow.models import Workflow, WorkflowVersion


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _create_workflow_and_version(
    session: Session,
    version: int = 1,
) -> tuple[str, str, int]:
    """Insert a workflow + version; return (wf_id, version_uuid, version_num)."""
    wf = Workflow(name="Alias Test WF", created_by="testuser")
    session.add(wf)
    session.flush()
    ver = WorkflowVersion(
        workflow_id=wf.id,
        version=version,
        definition_uri=f"s3://bucket/v{version}.wdl",
        created_by="testuser",
    )
    session.add(ver)
    session.commit()
    session.refresh(wf)
    session.refresh(ver)
    return str(wf.id), str(ver.id), ver.version


# ---------------------------------------------------------------------------
# PUT /workflows/{id}/aliases/{alias}
# ---------------------------------------------------------------------------

def test_set_alias(client: TestClient, session: Session):
    """Set the production alias."""
    wf_id, ver_id, ver_num = _create_workflow_and_version(session)

    body = {"version_num": ver_num}
    resp = client.put(
        f"/api/v1/workflows/{wf_id}/aliases/production",
        json=body,
    )
    assert resp.status_code == 200
    data = resp.json()

    assert data["alias"] == "production"
    assert data["workflow_version_id"] == ver_id
    assert data["version"] == 1
    assert data["workflow_id"] == wf_id
    assert data["created_by"] == "testuser"


def test_set_alias_development(
    client: TestClient, session: Session,
):
    """Set the development alias."""
    wf_id, ver_id, ver_num = _create_workflow_and_version(session)

    resp = client.put(
        f"/api/v1/workflows/{wf_id}/aliases/development",
        json={"version_num": ver_num},
    )
    assert resp.status_code == 200
    assert resp.json()["alias"] == "development"


def test_set_alias_custom_value(
    client: TestClient, session: Session,
):
    """Any free-text alias value is accepted."""
    wf_id, ver_id, ver_num = _create_workflow_and_version(session)

    resp = client.put(
        f"/api/v1/workflows/{wf_id}/aliases/staging",
        json={"version_num": ver_num},
    )
    assert resp.status_code == 200
    assert resp.json()["alias"] == "staging"


def test_move_alias_to_different_version(
    client: TestClient, session: Session,
):
    """Moving an alias to a new version works (upsert)."""
    wf = Workflow(name="Move Alias WF", created_by="testuser")
    session.add(wf)
    session.flush()
    v1 = WorkflowVersion(
        workflow_id=wf.id, version=1,
        definition_uri="s3://b/v1.wdl", created_by="testuser",
    )
    v2 = WorkflowVersion(
        workflow_id=wf.id, version=2,
        definition_uri="s3://b/v2.wdl", created_by="testuser",
    )
    session.add_all([v1, v2])
    session.commit()
    session.refresh(wf)
    session.refresh(v1)
    session.refresh(v2)

    wf_id = str(wf.id)

    # Set to v1
    resp1 = client.put(
        f"/api/v1/workflows/{wf_id}/aliases/production",
        json={"version_num": 1},
    )
    assert resp1.status_code == 200
    assert resp1.json()["version"] == 1

    # Move to v2
    resp2 = client.put(
        f"/api/v1/workflows/{wf_id}/aliases/production",
        json={"version_num": 2},
    )
    assert resp2.status_code == 200
    assert resp2.json()["version"] == 2


def test_set_alias_version_not_found(
    client: TestClient, session: Session,
):
    """Alias pointing to non-existent version returns 404."""
    wf = Workflow(name="No-Ver WF", created_by="testuser")
    session.add(wf)
    session.commit()
    session.refresh(wf)

    resp = client.put(
        f"/api/v1/workflows/{wf.id}/aliases/production",
        json={"version_num": 99},
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
    wf_id, ver_id, ver_num = _create_workflow_and_version(session)

    client.put(
        f"/api/v1/workflows/{wf_id}/aliases/production",
        json={"version_num": ver_num},
    )
    client.put(
        f"/api/v1/workflows/{wf_id}/aliases/development",
        json={"version_num": ver_num},
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
    wf_id, ver_id, ver_num = _create_workflow_and_version(session)

    client.put(
        f"/api/v1/workflows/{wf_id}/aliases/production",
        json={"version_num": ver_num},
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
# GET /workflows/{id}/aliases?alias=
# ---------------------------------------------------------------------------

def test_get_aliases_filter_by_alias(
    client: TestClient, session: Session,
):
    """Filter aliases by alias name returns only that alias."""
    wf_id, ver_id, ver_num = _create_workflow_and_version(session)

    client.put(
        f"/api/v1/workflows/{wf_id}/aliases/production",
        json={"version_num": ver_num},
    )
    client.put(
        f"/api/v1/workflows/{wf_id}/aliases/development",
        json={"version_num": ver_num},
    )

    resp = client.get(
        f"/api/v1/workflows/{wf_id}/aliases"
        f"?alias=production",
    )
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["alias"] == "production"


def test_get_aliases_filter_no_match(
    client: TestClient, session: Session,
):
    """Filter by alias that isn't set returns empty list."""
    wf_id, ver_id, ver_num = _create_workflow_and_version(session)

    client.put(
        f"/api/v1/workflows/{wf_id}/aliases/production",
        json={"version_num": ver_num},
    )

    resp = client.get(
        f"/api/v1/workflows/{wf_id}/aliases"
        f"?alias=development",
    )
    assert resp.status_code == 200
    assert resp.json() == []


# ---------------------------------------------------------------------------
# Workflow GET includes aliases
# ---------------------------------------------------------------------------

def test_workflow_public_includes_aliases(
    client: TestClient, session: Session,
):
    """GET /workflows/{id} includes nested alias data."""
    wf_id, ver_id, ver_num = _create_workflow_and_version(session)

    client.put(
        f"/api/v1/workflows/{wf_id}/aliases/production",
        json={"version_num": ver_num},
    )

    resp = client.get(f"/api/v1/workflows/{wf_id}")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["aliases"]) == 1
    assert data["aliases"][0]["alias"] == "production"
    assert data["aliases"][0]["version"] == 1
