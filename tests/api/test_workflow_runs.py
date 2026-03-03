"""Tests for WorkflowRun CRUD endpoints."""

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
        name="RNA-Seq Pipeline",
        definition_uri="s3://bucket/rnaseq.cwl",
        created_by="testuser",
    )
    session.add(wf)
    session.commit()
    session.refresh(wf)
    return str(wf.id)


def _seed_platforms(session: Session, extras: list[str] | None = None) -> None:
    """Ensure Arvados, SevenBridges (and any extras) exist as platforms."""
    for name in ["Arvados", "SevenBridges"]:
        session.add(Platform(name=name))
    for name in (extras or []):
        session.add(Platform(name=name))
    session.commit()


# ---------------------------------------------------------------------------
# POST /workflows/{id}/runs
# ---------------------------------------------------------------------------

def test_create_workflow_run(client: TestClient, session: Session):
    """Create a basic workflow run."""
    _seed_platforms(session)
    wf_id = _create_workflow(session)

    body = {
        "workflow_id": wf_id,
        "engine": "Arvados",
        "external_run_id": "arvados-run-001",
    }
    resp = client.post(f"/api/v1/workflows/{wf_id}/runs", json=body)
    assert resp.status_code == 201
    data = resp.json()

    assert data["workflow_id"] == wf_id
    assert data["workflow_name"] == "RNA-Seq Pipeline"
    assert data["engine"] == "Arvados"
    assert data["external_run_id"] == "arvados-run-001"
    assert data["created_by"] == "testuser"
    assert "id" in data
    assert "created_at" in data


def test_create_workflow_run_with_attributes(
    client: TestClient, session: Session,
):
    """Create a workflow run with key-value attributes."""
    _seed_platforms(session)
    wf_id = _create_workflow(session)

    body = {
        "workflow_id": wf_id,
        "engine": "SevenBridges",
        "external_run_id": "sb-task-001",
        "attributes": [
            {"key": "sample_count", "value": "42"},
            {"key": "priority", "value": "high"},
        ],
    }
    resp = client.post(f"/api/v1/workflows/{wf_id}/runs", json=body)
    assert resp.status_code == 201
    data = resp.json()

    assert data["external_run_id"] == "sb-task-001"
    assert len(data["attributes"]) == 2
    attr_keys = {a["key"] for a in data["attributes"]}
    assert attr_keys == {"sample_count", "priority"}


def test_create_workflow_run_workflow_not_found(client: TestClient):
    """Creating a run for a non-existent workflow returns 404."""
    fake_id = "00000000-0000-0000-0000-000000000000"
    body = {"workflow_id": fake_id, "engine": "Arvados", "external_run_id": "x"}
    resp = client.post(f"/api/v1/workflows/{fake_id}/runs", json=body)
    assert resp.status_code == 404


def test_create_workflow_run_invalid_engine(
    client: TestClient, session: Session,
):
    """Creating a run with an unregistered engine returns 400."""
    wf_id = _create_workflow(session)

    body = {"workflow_id": wf_id, "engine": "FakePlatform", "external_run_id": "x"}
    resp = client.post(f"/api/v1/workflows/{wf_id}/runs", json=body)
    assert resp.status_code == 400
    assert "not a registered platform" in resp.json()["detail"]


# ---------------------------------------------------------------------------
# GET /workflows/{id}/runs  (paginated)
# ---------------------------------------------------------------------------

def test_get_workflow_runs_empty(client: TestClient, session: Session):
    """Listing runs with none returns empty paginated response."""
    wf_id = _create_workflow(session)
    resp = client.get(f"/api/v1/workflows/{wf_id}/runs")
    assert resp.status_code == 200
    data = resp.json()

    assert data["data"] == []
    assert data["total_items"] == 0
    assert data["total_pages"] == 0
    assert data["current_page"] == 1
    assert data["has_next"] is False
    assert data["has_prev"] is False


def test_get_workflow_runs_paginated(client: TestClient, session: Session):
    """Verify pagination metadata is correct."""
    extras = [f"Engine{i}" for i in range(3)]
    _seed_platforms(session, extras=extras)
    wf_id = _create_workflow(session)

    # Create 3 runs
    for i in range(3):
        client.post(
            f"/api/v1/workflows/{wf_id}/runs",
            json={"workflow_id": wf_id, "engine": f"Engine{i}", "external_run_id": f"run-{i}"},
        )

    # Page 1, per_page=2
    resp = client.get(
        f"/api/v1/workflows/{wf_id}/runs",
        params={"per_page": 2, "page": 1},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["data"]) == 2
    assert data["total_items"] == 3
    assert data["total_pages"] == 2
    assert data["has_next"] is True
    assert data["has_prev"] is False

    # Page 2
    resp2 = client.get(
        f"/api/v1/workflows/{wf_id}/runs",
        params={"per_page": 2, "page": 2},
    )
    data2 = resp2.json()
    assert len(data2["data"]) == 1
    assert data2["has_next"] is False
    assert data2["has_prev"] is True


# ---------------------------------------------------------------------------
# GET /workflow-runs/{run_id}
# ---------------------------------------------------------------------------

def test_get_workflow_run_by_id(client: TestClient, session: Session):
    """Fetch a single workflow run by its ID."""
    _seed_platforms(session)
    wf_id = _create_workflow(session)

    create_resp = client.post(
        f"/api/v1/workflows/{wf_id}/runs",
        json={"workflow_id": wf_id, "engine": "Arvados", "external_run_id": "arv-run-1"},
    )
    run_id = create_resp.json()["id"]

    resp = client.get(f"/api/v1/workflow-runs/{run_id}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == run_id
    assert data["workflow_name"] == "RNA-Seq Pipeline"


def test_get_workflow_run_not_found(client: TestClient):
    """Fetching a non-existent workflow run returns 404."""
    fake_id = "00000000-0000-0000-0000-000000000000"
    resp = client.get(f"/api/v1/workflow-runs/{fake_id}")
    assert resp.status_code == 404


