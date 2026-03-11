"""Tests for WorkflowRegistration CRUD endpoints."""

from fastapi.testclient import TestClient
from sqlmodel import Session

from api.platforms.models import Platform
from api.workflow.models import Workflow


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _create_workflow(session: Session) -> str:
    """Insert a workflow directly and return its id as str."""
    wf = Workflow(
        name="WDL Alignment",
        definition_uri="s3://bucket/align.wdl",
        created_by="testuser",
    )
    session.add(wf)
    session.commit()
    session.refresh(wf)
    return str(wf.id)


def _seed_platforms(session: Session) -> None:
    """Ensure Arvados and SevenBridges platforms exist."""
    for name in ["Arvados", "SevenBridges"]:
        session.add(Platform(name=name))
    session.commit()


# ---------------------------------------------------------------------------
# POST /workflows/{id}/registrations
# ---------------------------------------------------------------------------

def test_create_registration(client: TestClient, session: Session):
    """Register a workflow on a platform engine."""
    _seed_platforms(session)
    wf_id = _create_workflow(session)

    body = {
        "engine": "Arvados",
        "external_id": "arvados-wf-abc123",
    }
    resp = client.post(f"/api/v1/workflows/{wf_id}/registrations", json=body)
    assert resp.status_code == 201
    data = resp.json()

    assert data["workflow_id"] == wf_id
    assert data["engine"] == "Arvados"
    assert data["external_id"] == "arvados-wf-abc123"
    assert data["created_by"] == "testuser"
    assert "id" in data
    assert "created_at" in data


def test_create_registration_minimal(client: TestClient, session: Session):
    """Only engine and external_id are required."""
    _seed_platforms(session)
    wf_id = _create_workflow(session)

    body = {"engine": "SevenBridges", "external_id": "sb-app-xyz"}
    resp = client.post(f"/api/v1/workflows/{wf_id}/registrations", json=body)
    assert resp.status_code == 201
    assert resp.json()["external_id"] == "sb-app-xyz"


def test_create_registration_duplicate_engine_conflict(
    client: TestClient, session: Session,
):
    """Duplicate (workflow_id, engine) pair returns 409."""
    _seed_platforms(session)
    wf_id = _create_workflow(session)

    body = {"engine": "Arvados", "external_id": "arvados-wf-1"}
    resp1 = client.post(f"/api/v1/workflows/{wf_id}/registrations", json=body)
    assert resp1.status_code == 201

    body2 = {"engine": "Arvados", "external_id": "arvados-wf-2"}
    resp2 = client.post(f"/api/v1/workflows/{wf_id}/registrations", json=body2)
    assert resp2.status_code == 409


def test_create_registration_workflow_not_found(client: TestClient):
    """Registration on a non-existent workflow returns 404."""
    fake_id = "00000000-0000-0000-0000-000000000000"
    body = {"engine": "Arvados", "external_id": "x"}
    resp = client.post(f"/api/v1/workflows/{fake_id}/registrations", json=body)
    assert resp.status_code == 404


def test_create_registration_invalid_engine(
    client: TestClient, session: Session,
):
    """Registration with an unregistered engine returns 400."""
    wf_id = _create_workflow(session)

    body = {"engine": "UnknownPlatform", "external_id": "x"}
    resp = client.post(f"/api/v1/workflows/{wf_id}/registrations", json=body)
    assert resp.status_code == 400
    assert "not a registered platform" in resp.json()["detail"]


# ---------------------------------------------------------------------------
# GET /workflows/{id}/registrations
# ---------------------------------------------------------------------------

def test_get_registrations_empty(client: TestClient, session: Session):
    """List registrations for a workflow with none returns empty list."""
    wf_id = _create_workflow(session)
    resp = client.get(f"/api/v1/workflows/{wf_id}/registrations")
    assert resp.status_code == 200
    assert resp.json() == []


def test_get_registrations_multiple(client: TestClient, session: Session):
    """List registrations after adding two different engines."""
    _seed_platforms(session)
    wf_id = _create_workflow(session)

    client.post(
        f"/api/v1/workflows/{wf_id}/registrations",
        json={"engine": "Arvados", "external_id": "arv-1"},
    )
    client.post(
        f"/api/v1/workflows/{wf_id}/registrations",
        json={"engine": "SevenBridges", "external_id": "sb-1"},
    )

    resp = client.get(f"/api/v1/workflows/{wf_id}/registrations")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 2
    engines = {r["engine"] for r in data}
    assert engines == {"Arvados", "SevenBridges"}


# ---------------------------------------------------------------------------
# DELETE /workflows/{id}/registrations/{registration_id}
# ---------------------------------------------------------------------------

def test_delete_registration(client: TestClient, session: Session):
    """Delete a registration returns 204 and it's gone."""
    _seed_platforms(session)
    wf_id = _create_workflow(session)

    create_resp = client.post(
        f"/api/v1/workflows/{wf_id}/registrations",
        json={"engine": "Arvados", "external_id": "arv-1"},
    )
    reg_id = create_resp.json()["id"]

    del_resp = client.delete(
        f"/api/v1/workflows/{wf_id}/registrations/{reg_id}"
    )
    assert del_resp.status_code == 204

    # Verify it's gone
    list_resp = client.get(f"/api/v1/workflows/{wf_id}/registrations")
    assert list_resp.json() == []


def test_delete_registration_not_found(
    client: TestClient, session: Session,
):
    """Deleting a non-existent registration returns 404."""
    wf_id = _create_workflow(session)
    fake_reg_id = "00000000-0000-0000-0000-000000000000"

    resp = client.delete(
        f"/api/v1/workflows/{wf_id}/registrations/{fake_reg_id}"
    )
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Workflow GET response includes registrations
# ---------------------------------------------------------------------------

def test_workflow_public_includes_registrations(
    client: TestClient, session: Session,
):
    """GET /workflows/{id} includes nested registration data."""
    _seed_platforms(session)
    wf_id = _create_workflow(session)

    client.post(
        f"/api/v1/workflows/{wf_id}/registrations",
        json={"engine": "Arvados", "external_id": "arv-1"},
    )

    resp = client.get(f"/api/v1/workflows/{wf_id}")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["registrations"]) == 1
    assert data["registrations"][0]["engine"] == "Arvados"
