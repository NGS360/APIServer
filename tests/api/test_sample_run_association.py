"""Tests for Sample ↔ SequencingRun association endpoints."""

from datetime import date

from fastapi.testclient import TestClient
from sqlmodel import Session

from api.project.models import Project
from api.project.services import generate_project_id
from api.runs.models import SequencingRun
from api.samples.models import Sample


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _create_run(session: Session) -> str:
    """Insert a sequencing run and return its barcode."""
    run = SequencingRun(
        run_date=date(2024, 3, 15),
        machine_id="M00001",
        run_number=42,
        flowcell_id="HXXXXXXXXX",
        experiment_name="TestExp",
    )
    session.add(run)
    session.commit()
    session.refresh(run)
    return run.barcode


def _create_sample(session: Session) -> str:
    """Insert a project + sample and return the sample id (UUID str)."""
    project = Project(name="Test Project")
    project.project_id = generate_project_id(session=session)
    project.attributes = []
    session.add(project)
    session.flush()

    sample = Sample(sample_id="SAMPLE_001", project_id=project.project_id)
    session.add(sample)
    session.commit()
    session.refresh(sample)
    return str(sample.id)


# ---------------------------------------------------------------------------
# POST /runs/{barcode}/samples
# ---------------------------------------------------------------------------

def test_associate_sample_with_run(client: TestClient, session: Session):
    """Associate a sample with a sequencing run."""
    barcode = _create_run(session)
    sample_id = _create_sample(session)

    resp = client.post(
        f"/api/v1/runs/{barcode}/samples",
        json={"sample_id": sample_id},
    )
    assert resp.status_code == 201
    data = resp.json()

    assert data["sample_id"] == sample_id
    assert data["created_by"] == "testuser"
    assert "id" in data
    assert "sequencing_run_id" in data
    assert "created_at" in data


def test_associate_sample_duplicate_conflict(client: TestClient, session: Session):
    """Associating the same sample twice returns 409."""
    barcode = _create_run(session)
    sample_id = _create_sample(session)

    resp1 = client.post(
        f"/api/v1/runs/{barcode}/samples",
        json={"sample_id": sample_id},
    )
    assert resp1.status_code == 201

    resp2 = client.post(
        f"/api/v1/runs/{barcode}/samples",
        json={"sample_id": sample_id},
    )
    assert resp2.status_code == 409


def test_associate_sample_run_not_found(client: TestClient, session: Session):
    """Associating with a non-existent run returns 404."""
    sample_id = _create_sample(session)
    resp = client.post(
        "/api/v1/runs/240101_NOEXIST_0001_FAKECELL/samples",
        json={"sample_id": sample_id},
    )
    assert resp.status_code == 404


def test_associate_sample_sample_not_found(client: TestClient, session: Session):
    """Associating a non-existent sample returns 404."""
    barcode = _create_run(session)
    fake_sample = "00000000-0000-0000-0000-000000000000"

    resp = client.post(
        f"/api/v1/runs/{barcode}/samples",
        json={"sample_id": fake_sample},
    )
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# GET /runs/{barcode}/samples
# ---------------------------------------------------------------------------

def test_get_samples_for_run_empty(client: TestClient, session: Session):
    """Listing samples for a run with no associations returns empty list."""
    barcode = _create_run(session)
    resp = client.get(f"/api/v1/runs/{barcode}/samples")
    assert resp.status_code == 200
    assert resp.json() == []


def test_get_samples_for_run(client: TestClient, session: Session):
    """List sample associations after adding one."""
    barcode = _create_run(session)
    sample_id = _create_sample(session)

    client.post(
        f"/api/v1/runs/{barcode}/samples",
        json={"sample_id": sample_id},
    )

    resp = client.get(f"/api/v1/runs/{barcode}/samples")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["sample_id"] == sample_id


def test_get_samples_for_run_not_found(client: TestClient):
    """Listing samples for a non-existent run returns 404."""
    resp = client.get("/api/v1/runs/240101_NOEXIST_0001_FAKECELL/samples")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# DELETE /runs/{barcode}/samples/{sample_id}
# ---------------------------------------------------------------------------

def test_remove_sample_from_run(client: TestClient, session: Session):
    """Remove a sample association from a run."""
    barcode = _create_run(session)
    sample_id = _create_sample(session)

    client.post(
        f"/api/v1/runs/{barcode}/samples",
        json={"sample_id": sample_id},
    )

    resp = client.delete(f"/api/v1/runs/{barcode}/samples/{sample_id}")
    assert resp.status_code == 204

    # Verify it's gone
    list_resp = client.get(f"/api/v1/runs/{barcode}/samples")
    assert list_resp.json() == []


def test_remove_sample_from_run_not_found(client: TestClient, session: Session):
    """Removing a non-associated sample returns 404."""
    barcode = _create_run(session)
    fake_sample = "00000000-0000-0000-0000-000000000000"

    resp = client.delete(f"/api/v1/runs/{barcode}/samples/{fake_sample}")
    assert resp.status_code == 404
