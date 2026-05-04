"""Tests for Pipeline CRUD and Pipeline ↔ Workflow association endpoints."""

from fastapi.testclient import TestClient
from sqlmodel import Session

from api.workflow.models import Workflow


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _create_workflow(session: Session, name: str = "Align Reads") -> str:
    """Insert a workflow directly and return its id as str."""
    wf = Workflow(
        name=name,
        definition_uri=f"s3://bucket/{name.lower().replace(' ', '-')}.wdl",
        created_by="testuser",
    )
    session.add(wf)
    session.commit()
    session.refresh(wf)
    return str(wf.id)


# ---------------------------------------------------------------------------
# POST /pipelines
# ---------------------------------------------------------------------------

def test_create_pipeline(client: TestClient):
    """Create a pipeline with name only."""
    body = {"name": "WGS Pipeline"}
    resp = client.post("/api/v1/pipelines", json=body)
    assert resp.status_code == 201
    data = resp.json()

    assert data["name"] == "WGS Pipeline"
    assert data["version"] is None
    assert data["created_by"] == "testuser"
    assert "id" in data
    assert "created_at" in data


def test_create_pipeline_with_version_and_attributes(client: TestClient):
    """Create a pipeline with version and attributes."""
    body = {
        "name": "RNA Pipeline",
        "version": "3.0.0",
        "attributes": [
            {"key": "organism", "value": "human"},
            {"key": "assay", "value": "rna-seq"},
        ],
    }
    resp = client.post("/api/v1/pipelines", json=body)
    assert resp.status_code == 201
    data = resp.json()

    assert data["version"] == "3.0.0"
    assert len(data["attributes"]) == 2
    attr_keys = {a["key"] for a in data["attributes"]}
    assert attr_keys == {"organism", "assay"}


def test_create_pipeline_rejects_case_insensitive_duplicate_attributes(
    client: TestClient,
):
    """Duplicate attribute keys differing only in case should be rejected."""
    body = {
        "name": "Dup Attr Pipeline",
        "attributes": [
            {"key": "Organism", "value": "human"},
            {"key": "organism", "value": "mouse"},
        ],
    }
    resp = client.post("/api/v1/pipelines", json=body)
    assert resp.status_code == 400
    assert "duplicate" in resp.json()["detail"].lower()


def test_create_pipeline_with_workflow_ids(client: TestClient, session: Session):
    """Create a pipeline pre-linked to existing workflows."""
    wf1_id = _create_workflow(session, "Step 1 - Trim")
    wf2_id = _create_workflow(session, "Step 2 - Align")

    body = {
        "name": "Full Pipeline",
        "workflow_ids": [wf1_id, wf2_id],
    }
    resp = client.post("/api/v1/pipelines", json=body)
    assert resp.status_code == 201
    data = resp.json()

    assert len(data["workflows"]) == 2
    wf_names = {w["name"] for w in data["workflows"]}
    assert "Step 1 - Trim" in wf_names
    assert "Step 2 - Align" in wf_names


def test_create_pipeline_with_invalid_workflow_id(client: TestClient):
    """Creating a pipeline with a non-existent workflow id returns 404."""
    fake_id = "00000000-0000-0000-0000-000000000000"
    body = {"name": "Bad Pipeline", "workflow_ids": [fake_id]}
    resp = client.post("/api/v1/pipelines", json=body)
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# GET /pipelines  (paginated)
# ---------------------------------------------------------------------------

def test_get_pipelines_empty(client: TestClient):
    """Listing pipelines when none exist returns empty paginated response."""
    resp = client.get("/api/v1/pipelines")
    assert resp.status_code == 200
    data = resp.json()

    assert data["data"] == []
    assert data["total_items"] == 0


def test_get_pipelines_paginated(client: TestClient):
    """Verify pagination works correctly."""
    # Create 3 pipelines
    for i in range(3):
        client.post("/api/v1/pipelines", json={"name": f"Pipeline {i}"})

    resp = client.get("/api/v1/pipelines", params={"per_page": 2, "page": 1})
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["data"]) == 2
    assert data["total_items"] == 3
    assert data["total_pages"] == 2
    assert data["has_next"] is True

    resp2 = client.get("/api/v1/pipelines", params={"per_page": 2, "page": 2})
    data2 = resp2.json()
    assert len(data2["data"]) == 1
    assert data2["has_prev"] is True


# ---------------------------------------------------------------------------
# GET /pipelines/{pipeline_id}
# ---------------------------------------------------------------------------

def test_get_pipeline_by_id(client: TestClient):
    """Fetch a single pipeline by its ID."""
    create_resp = client.post(
        "/api/v1/pipelines", json={"name": "My Pipeline", "version": "1.0"}
    )
    pipeline_id = create_resp.json()["id"]

    resp = client.get(f"/api/v1/pipelines/{pipeline_id}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == pipeline_id
    assert data["name"] == "My Pipeline"
    assert data["version"] == "1.0"


def test_get_pipeline_not_found(client: TestClient):
    """Fetching a non-existent pipeline returns 404."""
    fake_id = "00000000-0000-0000-0000-000000000000"
    resp = client.get(f"/api/v1/pipelines/{fake_id}")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# POST /pipelines/{pipeline_id}/workflows  (add workflow association)
# ---------------------------------------------------------------------------

def test_add_workflow_to_pipeline(client: TestClient, session: Session):
    """Associate a workflow with an existing pipeline."""
    wf_id = _create_workflow(session)

    create_resp = client.post(
        "/api/v1/pipelines", json={"name": "My Pipeline"}
    )
    pipeline_id = create_resp.json()["id"]

    resp = client.post(
        f"/api/v1/pipelines/{pipeline_id}/workflows",
        params={"workflow_id": wf_id},
    )
    assert resp.status_code == 201
    data = resp.json()
    assert "id" in data
    assert data["message"] == "Workflow added to pipeline."

    # Verify it appears in the pipeline detail
    detail = client.get(f"/api/v1/pipelines/{pipeline_id}").json()
    assert len(detail["workflows"]) == 1
    assert detail["workflows"][0]["name"] == "Align Reads"


def test_add_workflow_to_pipeline_duplicate(client: TestClient, session: Session):
    """Adding same workflow twice returns 409."""
    wf_id = _create_workflow(session)

    create_resp = client.post(
        "/api/v1/pipelines", json={"name": "Dup Test"}
    )
    pipeline_id = create_resp.json()["id"]

    client.post(
        f"/api/v1/pipelines/{pipeline_id}/workflows",
        params={"workflow_id": wf_id},
    )
    resp2 = client.post(
        f"/api/v1/pipelines/{pipeline_id}/workflows",
        params={"workflow_id": wf_id},
    )
    assert resp2.status_code == 409


def test_add_workflow_to_pipeline_workflow_not_found(client: TestClient):
    """Adding a non-existent workflow returns 404."""
    create_resp = client.post(
        "/api/v1/pipelines", json={"name": "Pipeline"}
    )
    pipeline_id = create_resp.json()["id"]
    fake_wf = "00000000-0000-0000-0000-000000000000"

    resp = client.post(
        f"/api/v1/pipelines/{pipeline_id}/workflows",
        params={"workflow_id": fake_wf},
    )
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# DELETE /pipelines/{pipeline_id}/workflows/{workflow_id}
# ---------------------------------------------------------------------------

def test_remove_workflow_from_pipeline(client: TestClient, session: Session):
    """Remove a workflow from a pipeline."""
    wf_id = _create_workflow(session)

    create_resp = client.post(
        "/api/v1/pipelines", json={"name": "Pipeline"}
    )
    pipeline_id = create_resp.json()["id"]

    # Add and then remove
    client.post(
        f"/api/v1/pipelines/{pipeline_id}/workflows",
        params={"workflow_id": wf_id},
    )

    resp = client.delete(
        f"/api/v1/pipelines/{pipeline_id}/workflows/{wf_id}"
    )
    assert resp.status_code == 204

    # Verify it's gone
    detail = client.get(f"/api/v1/pipelines/{pipeline_id}").json()
    assert detail["workflows"] is None or len(detail["workflows"]) == 0


def test_remove_workflow_from_pipeline_not_found(client: TestClient):
    """Removing a non-associated workflow returns 404."""
    create_resp = client.post(
        "/api/v1/pipelines", json={"name": "Pipeline"}
    )
    pipeline_id = create_resp.json()["id"]
    fake_wf = "00000000-0000-0000-0000-000000000000"

    resp = client.delete(
        f"/api/v1/pipelines/{pipeline_id}/workflows/{fake_wf}"
    )
    assert resp.status_code == 404
