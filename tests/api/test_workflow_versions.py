"""Tests for WorkflowVersion CRUD endpoints."""

from fastapi.testclient import TestClient
from sqlmodel import Session

from api.workflow.models import Workflow


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _create_workflow(session: Session) -> str:
    """Insert a workflow directly and return its id as str."""
    wf = Workflow(
        name="WDL Alignment",
        created_by="testuser",
    )
    session.add(wf)
    session.commit()
    session.refresh(wf)
    return str(wf.id)


# ---------------------------------------------------------------------------
# POST /workflows/{id}/versions
# ---------------------------------------------------------------------------

def test_create_version(client: TestClient, session: Session):
    """Create a new version for a workflow."""
    wf_id = _create_workflow(session)

    body = {
        "version": "1.0.0",
        "definition_uri": "s3://bucket/align-v1.0.wdl",
    }
    resp = client.post(
        f"/api/v1/workflows/{wf_id}/versions", json=body,
    )
    assert resp.status_code == 201
    data = resp.json()

    assert data["workflow_id"] == wf_id
    assert data["version"] == "1.0.0"
    assert data["definition_uri"] == "s3://bucket/align-v1.0.wdl"
    assert data["created_by"] == "testuser"
    assert "id" in data
    assert "created_at" in data


def test_create_version_duplicate_conflict(
    client: TestClient, session: Session,
):
    """Duplicate version string returns 409."""
    wf_id = _create_workflow(session)

    body = {
        "version": "1.0.0",
        "definition_uri": "s3://bucket/align-v1.0.wdl",
    }
    resp1 = client.post(
        f"/api/v1/workflows/{wf_id}/versions", json=body,
    )
    assert resp1.status_code == 201

    body2 = {
        "version": "1.0.0",
        "definition_uri": "s3://bucket/align-v1.0-alt.wdl",
    }
    resp2 = client.post(
        f"/api/v1/workflows/{wf_id}/versions", json=body2,
    )
    assert resp2.status_code == 409


def test_create_version_workflow_not_found(client: TestClient):
    """Version on a non-existent workflow returns 404."""
    fake_id = "00000000-0000-0000-0000-000000000000"
    body = {
        "version": "1.0.0",
        "definition_uri": "s3://bucket/x.wdl",
    }
    resp = client.post(
        f"/api/v1/workflows/{fake_id}/versions", json=body,
    )
    assert resp.status_code == 404


def test_create_multiple_versions(
    client: TestClient, session: Session,
):
    """Multiple distinct versions are allowed."""
    wf_id = _create_workflow(session)

    for v in ["1.0.0", "2.0.0", "3.0.0"]:
        resp = client.post(
            f"/api/v1/workflows/{wf_id}/versions",
            json={
                "version": v,
                "definition_uri": f"s3://bucket/align-{v}.wdl",
            },
        )
        assert resp.status_code == 201


# ---------------------------------------------------------------------------
# GET /workflows/{id}/versions
# ---------------------------------------------------------------------------

def test_get_versions_empty(
    client: TestClient, session: Session,
):
    """List versions for a workflow with none."""
    wf_id = _create_workflow(session)
    resp = client.get(
        f"/api/v1/workflows/{wf_id}/versions",
    )
    assert resp.status_code == 200
    assert resp.json() == []


def test_get_versions_multiple(
    client: TestClient, session: Session,
):
    """List versions after adding two."""
    wf_id = _create_workflow(session)

    for v in ["1.0.0", "2.0.0"]:
        client.post(
            f"/api/v1/workflows/{wf_id}/versions",
            json={
                "version": v,
                "definition_uri": f"s3://bucket/{v}.wdl",
            },
        )

    resp = client.get(
        f"/api/v1/workflows/{wf_id}/versions",
    )
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 2
    versions = {v["version"] for v in data}
    assert versions == {"1.0.0", "2.0.0"}


# ---------------------------------------------------------------------------
# GET /workflows/{id}/versions/{version_id}
# ---------------------------------------------------------------------------

def test_get_version_by_id(
    client: TestClient, session: Session,
):
    """Fetch a single version by its ID."""
    wf_id = _create_workflow(session)

    create_resp = client.post(
        f"/api/v1/workflows/{wf_id}/versions",
        json={
            "version": "1.0.0",
            "definition_uri": "s3://bucket/v1.wdl",
        },
    )
    version_id = create_resp.json()["id"]

    resp = client.get(
        f"/api/v1/workflows/{wf_id}/versions/{version_id}",
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == version_id
    assert data["version"] == "1.0.0"


# ---------------------------------------------------------------------------
# Workflow GET includes versions
# ---------------------------------------------------------------------------

def test_workflow_public_includes_versions(
    client: TestClient, session: Session,
):
    """GET /workflows/{id} includes nested version data."""
    wf_id = _create_workflow(session)

    client.post(
        f"/api/v1/workflows/{wf_id}/versions",
        json={
            "version": "1.0.0",
            "definition_uri": "s3://bucket/v1.wdl",
        },
    )

    resp = client.get(f"/api/v1/workflows/{wf_id}")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["versions"]) == 1
    assert data["versions"][0]["version"] == "1.0.0"
