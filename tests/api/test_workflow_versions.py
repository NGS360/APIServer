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
    """Create a new/initial version for a workflow """
    wf_id = _create_workflow(session)

    body = {
        "definition_uri": "s3://bucket/align-v1.0.wdl",
        "attributes": [
            {"key": "attributefield1", "value": "value1"},
            {"key": "attributefield2", "value": "value2"},
        ],
    }
    resp = client.post(
        f"/api/v1/workflows/{wf_id}/versions", json=body,
    )
    assert resp.status_code == 201
    data = resp.json()

    assert data["workflow_id"] == wf_id
    assert data["version"] == 1
    assert data["definition_uri"] == "s3://bucket/align-v1.0.wdl"
    assert data["created_by"] == "testuser"
    assert "id" in data
    assert "created_at" in data
    assert "attributes" in data
    assert len(data["attributes"]) == 2
    assert data["attributes"][0]["key"] == "attributefield1"
    assert data["attributes"][0]["value"] == "value1"
    assert data["attributes"][1]["key"] == "attributefield2"
    assert data["attributes"][1]["value"] == "value2"


def test_create_version_workflow_not_found(client: TestClient):
    """Version on a non-existent workflow returns 404."""
    fake_id = "00000000-0000-0000-0000-000000000000"
    body = {
        "definition_uri": "s3://bucket/x.wdl",
    }
    resp = client.post(
        f"/api/v1/workflows/{fake_id}/versions", json=body,
    )
    assert resp.status_code == 404


def test_create_multiple_versions_auto_increment(
    client: TestClient, session: Session,
):
    """Multiple versions are auto-incremented (1, 2, 3)."""
    wf_id = _create_workflow(session)

    expected_versions = []
    for i in range(1, 4):
        resp = client.post(
            f"/api/v1/workflows/{wf_id}/versions",
            json={
                "definition_uri": f"s3://bucket/align-v{i}.wdl",
            },
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["version"] == i
        expected_versions.append(i)

    assert expected_versions == [1, 2, 3]


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

    for _ in range(2):
        client.post(
            f"/api/v1/workflows/{wf_id}/versions",
            json={
                "definition_uri": "s3://bucket/align.wdl",
            },
        )

    resp = client.get(
        f"/api/v1/workflows/{wf_id}/versions",
    )
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 2
    versions = {v["version"] for v in data}
    assert versions == {1, 2}


# ---------------------------------------------------------------------------
# GET /workflows/{id}/versions/{version_num}
# ---------------------------------------------------------------------------

def test_get_version_by_num(
    client: TestClient, session: Session,
):
    """Fetch a single version by its version number."""
    wf_id = _create_workflow(session)

    create_resp = client.post(
        f"/api/v1/workflows/{wf_id}/versions",
        json={
            "definition_uri": "s3://bucket/v1.wdl",
        },
    )
    assert create_resp.status_code == 201
    version_id = create_resp.json()["id"]

    resp = client.get(
        f"/api/v1/workflows/{wf_id}/versions/1",
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == version_id
    assert data["version"] == 1


def test_get_version_by_num_not_found(
    client: TestClient, session: Session,
):
    """Fetch a non-existent version number returns 404."""
    wf_id = _create_workflow(session)

    resp = client.get(
        f"/api/v1/workflows/{wf_id}/versions/99",
    )
    assert resp.status_code == 404


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
            "definition_uri": "s3://bucket/v1.wdl",
        },
    )

    resp = client.get(f"/api/v1/workflows/{wf_id}")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["versions"]) == 1
    assert data["versions"][0]["version"] == 1


# ---------------------------------------------------------------------------
# inputs / outputs
# ---------------------------------------------------------------------------

def test_create_version_with_inputs_and_outputs(
    client: TestClient, session: Session,
):
    """Inputs and outputs round-trip through create and GET."""
    wf_id = _create_workflow(session)

    body = {
        "definition_uri": "s3://bucket/align.cwl",
        "inputs": [
            {
                "id": "reference_genome",
                "type": "File",
                "required": True,
                "doc": "Reference genome FASTA.",
            },
            {
                "id": "bait_set_name",
                "type": "string?",
                "required": False,
                "doc": "Name of bait set.",
                "default": None,
            },
            {
                "id": "coverage_threshold",
                "type": "int",
                "required": False,
                "default": 30,
            },
        ],
        "outputs": [
            {
                "id": "AlignmentSummaryMetrics",
                "type": "File",
                "doc": "Alignment Summary Metrics.",
            },
            {
                "id": "OutputBAM",
                "type": "File",
            },
        ],
    }
    resp = client.post(
        f"/api/v1/workflows/{wf_id}/versions", json=body,
    )
    assert resp.status_code == 201, resp.text
    data = resp.json()

    assert len(data["inputs"]) == 3
    assert data["inputs"][0]["id"] == "reference_genome"
    assert data["inputs"][0]["required"] is True
    assert data["inputs"][1]["required"] is False
    assert data["inputs"][2]["default"] == 30

    assert len(data["outputs"]) == 2
    assert data["outputs"][0]["id"] == "AlignmentSummaryMetrics"
    assert "required" not in data["outputs"][0]

    # Same data on GET
    ver_num = data["version"]
    get_resp = client.get(
        f"/api/v1/workflows/{wf_id}/versions/{ver_num}",
    )
    assert get_resp.status_code == 200
    got = get_resp.json()
    assert got["inputs"] == data["inputs"]
    assert got["outputs"] == data["outputs"]


def test_create_version_without_inputs_outputs(
    client: TestClient, session: Session,
):
    """Omitting inputs/outputs stores NULL and round-trips as None."""
    wf_id = _create_workflow(session)
    resp = client.post(
        f"/api/v1/workflows/{wf_id}/versions",
        json={"definition_uri": "s3://bucket/v.cwl"},
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["inputs"] is None
    assert data["outputs"] is None


def test_create_version_input_missing_required_field(
    client: TestClient, session: Session,
):
    """Server rejects an input entry missing 'required'."""
    wf_id = _create_workflow(session)
    resp = client.post(
        f"/api/v1/workflows/{wf_id}/versions",
        json={
            "definition_uri": "s3://bucket/v.cwl",
            "inputs": [
                {"id": "x", "type": "File"},  # missing 'required'
            ],
        },
    )
    assert resp.status_code == 422


def test_create_version_output_missing_required_field(
    client: TestClient, session: Session,
):
    """Server rejects an output entry missing 'id'."""
    wf_id = _create_workflow(session)
    resp = client.post(
        f"/api/v1/workflows/{wf_id}/versions",
        json={
            "definition_uri": "s3://bucket/v.cwl",
            "outputs": [
                {"type": "File"},  # missing 'id'
            ],
        },
    )
    assert resp.status_code == 422
