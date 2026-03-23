"""Tests for WorkflowRegistration CRUD endpoints."""

from fastapi.testclient import TestClient
from sqlmodel import Session

from api.platforms.models import Platform
from api.workflow.models import Workflow, WorkflowVersion


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _create_workflow_and_version(
    session: Session,
) -> tuple[str, str]:
    """Insert a workflow + version; return (wf_id, version_id)."""
    wf = Workflow(
        name="WDL Alignment",
        created_by="testuser",
    )
    session.add(wf)
    session.flush()
    ver = WorkflowVersion(
        workflow_id=wf.id,
        version="1.0.0",
        definition_uri="s3://bucket/align.wdl",
        created_by="testuser",
    )
    session.add(ver)
    session.commit()
    session.refresh(wf)
    session.refresh(ver)
    return str(wf.id), str(ver.id)


def _seed_platforms(session: Session) -> None:
    """Ensure Arvados and SevenBridges platforms exist."""
    for name in ["Arvados", "SevenBridges"]:
        session.add(Platform(name=name))
    session.commit()


# ---------------------------------------------------------------------------
# POST /workflows/{id}/versions/{vid}/registrations
# ---------------------------------------------------------------------------

def test_create_registration(
    client: TestClient, session: Session,
):
    """Register a workflow version on a platform engine."""
    _seed_platforms(session)
    wf_id, ver_id = _create_workflow_and_version(session)

    body = {
        "engine": "Arvados",
        "external_id": "arvados-wf-abc123",
    }
    resp = client.post(
        f"/api/v1/workflows/{wf_id}/versions/{ver_id}"
        f"/registrations",
        json=body,
    )
    assert resp.status_code == 201
    data = resp.json()

    assert data["workflow_version_id"] == ver_id
    assert data["engine"] == "Arvados"
    assert data["external_id"] == "arvados-wf-abc123"
    assert data["created_by"] == "testuser"
    assert "id" in data
    assert "created_at" in data


def test_create_registration_minimal(
    client: TestClient, session: Session,
):
    """Only engine and external_id are required."""
    _seed_platforms(session)
    wf_id, ver_id = _create_workflow_and_version(session)

    body = {
        "engine": "SevenBridges",
        "external_id": "sb-app-xyz",
    }
    resp = client.post(
        f"/api/v1/workflows/{wf_id}/versions/{ver_id}"
        f"/registrations",
        json=body,
    )
    assert resp.status_code == 201
    assert resp.json()["external_id"] == "sb-app-xyz"


def test_create_registration_duplicate_engine_conflict(
    client: TestClient, session: Session,
):
    """Duplicate (version_id, engine) pair returns 409."""
    _seed_platforms(session)
    wf_id, ver_id = _create_workflow_and_version(session)

    body = {"engine": "Arvados", "external_id": "arv-1"}
    resp1 = client.post(
        f"/api/v1/workflows/{wf_id}/versions/{ver_id}"
        f"/registrations",
        json=body,
    )
    assert resp1.status_code == 201

    body2 = {"engine": "Arvados", "external_id": "arv-2"}
    resp2 = client.post(
        f"/api/v1/workflows/{wf_id}/versions/{ver_id}"
        f"/registrations",
        json=body2,
    )
    assert resp2.status_code == 409


def test_create_registration_version_not_found(
    client: TestClient, session: Session,
):
    """Registration on a non-existent version returns 404."""
    _seed_platforms(session)
    wf = Workflow(name="WF", created_by="testuser")
    session.add(wf)
    session.commit()
    session.refresh(wf)

    fake_ver = "00000000-0000-0000-0000-000000000000"
    body = {"engine": "Arvados", "external_id": "x"}
    resp = client.post(
        f"/api/v1/workflows/{wf.id}/versions/{fake_ver}"
        f"/registrations",
        json=body,
    )
    assert resp.status_code == 404


def test_create_registration_invalid_engine(
    client: TestClient, session: Session,
):
    """Registration with an unregistered engine returns 400."""
    wf_id, ver_id = _create_workflow_and_version(session)

    body = {"engine": "UnknownPlatform", "external_id": "x"}
    resp = client.post(
        f"/api/v1/workflows/{wf_id}/versions/{ver_id}"
        f"/registrations",
        json=body,
    )
    assert resp.status_code == 400
    assert "not a registered platform" in resp.json()["detail"]


# ---------------------------------------------------------------------------
# GET /workflows/{id}/versions/{vid}/registrations
# ---------------------------------------------------------------------------

def test_get_registrations_empty(
    client: TestClient, session: Session,
):
    """List registrations for a version with none."""
    wf_id, ver_id = _create_workflow_and_version(session)
    resp = client.get(
        f"/api/v1/workflows/{wf_id}/versions/{ver_id}"
        f"/registrations",
    )
    assert resp.status_code == 200
    assert resp.json() == []


def test_get_registrations_multiple(
    client: TestClient, session: Session,
):
    """List registrations after adding two engines."""
    _seed_platforms(session)
    wf_id, ver_id = _create_workflow_and_version(session)

    client.post(
        f"/api/v1/workflows/{wf_id}/versions/{ver_id}"
        f"/registrations",
        json={"engine": "Arvados", "external_id": "arv-1"},
    )
    client.post(
        f"/api/v1/workflows/{wf_id}/versions/{ver_id}"
        f"/registrations",
        json={
            "engine": "SevenBridges",
            "external_id": "sb-1",
        },
    )

    resp = client.get(
        f"/api/v1/workflows/{wf_id}/versions/{ver_id}"
        f"/registrations",
    )
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 2
    engines = {r["engine"] for r in data}
    assert engines == {"Arvados", "SevenBridges"}


# ---------------------------------------------------------------------------
# DELETE .../registrations/{registration_id}
# ---------------------------------------------------------------------------

def test_delete_registration(
    client: TestClient, session: Session,
):
    """Delete a registration returns 204 and it's gone."""
    _seed_platforms(session)
    wf_id, ver_id = _create_workflow_and_version(session)

    create_resp = client.post(
        f"/api/v1/workflows/{wf_id}/versions/{ver_id}"
        f"/registrations",
        json={"engine": "Arvados", "external_id": "arv-1"},
    )
    reg_id = create_resp.json()["id"]

    del_resp = client.delete(
        f"/api/v1/workflows/{wf_id}/versions/{ver_id}"
        f"/registrations/{reg_id}",
    )
    assert del_resp.status_code == 204

    # Verify it's gone
    list_resp = client.get(
        f"/api/v1/workflows/{wf_id}/versions/{ver_id}"
        f"/registrations",
    )
    assert list_resp.json() == []


def test_delete_registration_not_found(
    client: TestClient, session: Session,
):
    """Deleting a non-existent registration returns 404."""
    wf_id, ver_id = _create_workflow_and_version(session)
    fake_reg = "00000000-0000-0000-0000-000000000000"

    resp = client.delete(
        f"/api/v1/workflows/{wf_id}/versions/{ver_id}"
        f"/registrations/{fake_reg}",
    )
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Version GET includes registrations
# ---------------------------------------------------------------------------

def test_version_public_includes_registrations(
    client: TestClient, session: Session,
):
    """GET version includes nested registration data."""
    _seed_platforms(session)
    wf_id, ver_id = _create_workflow_and_version(session)

    client.post(
        f"/api/v1/workflows/{wf_id}/versions/{ver_id}"
        f"/registrations",
        json={"engine": "Arvados", "external_id": "arv-1"},
    )

    resp = client.get(
        f"/api/v1/workflows/{wf_id}/versions/{ver_id}",
    )
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["registrations"]) == 1
    assert data["registrations"][0]["engine"] == "Arvados"
