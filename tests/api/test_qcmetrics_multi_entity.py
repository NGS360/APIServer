"""
Tests for Phase 3: QC Multi-Entity Extension.

Tests the direct FK scoping on QCMetric (sequencing_run_id, workflow_run_id)
and the workflow_run_id provenance FK on QCRecord.
"""
from datetime import date
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlmodel import Session

from api.runs.models import SequencingRun
from api.workflow.models import Workflow, WorkflowRun
from api.platforms.models import Platform


# ---------------------------------------------------------------------------
# Helper fixtures — create prerequisite entities directly in DB
# ---------------------------------------------------------------------------


def _ensure_platform(session: Session, name: str = "Arvados") -> str:
    """Ensure a Platform record exists; return its name."""
    existing = session.get(Platform, name)
    if not existing:
        session.add(Platform(name=name))
        session.flush()
    return name


def _create_workflow(session: Session) -> Workflow:
    """Create a minimal Workflow and return it."""
    wf = Workflow(
        name="RNA-Seq Pipeline",
        version="1.0",
        definition_uri="https://github.com/test/rna-seq.wdl",
        created_by="testuser",
    )
    session.add(wf)
    session.flush()
    return wf


def _create_workflow_run(session: Session) -> str:
    """Create Platform → Workflow → WorkflowRun chain; return run ID as str."""
    engine = _ensure_platform(session)
    wf = _create_workflow(session)
    wr = WorkflowRun(
        workflow_id=wf.id,
        engine=engine,
        external_run_id=f"ext-run-{uuid4().hex[:8]}",
        created_by="testuser",
    )
    session.add(wr)
    session.flush()
    wr_id = str(wr.id)
    session.commit()
    return wr_id


def _create_sequencing_run(session: Session) -> str:
    """Create a SequencingRun; return its ID as str."""
    sr = SequencingRun(
        id=uuid4(),
        run_date=date(2024, 6, 15),
        machine_id="M00001",
        run_number=42,
        flowcell_id=f"H{uuid4().hex[:8].upper()}",
    )
    session.add(sr)
    session.flush()
    sr_id = str(sr.id)
    session.commit()
    return sr_id


# ============================================================================
# Provenance: QCRecord.workflow_run_id
# ============================================================================


def test_create_qcrecord_with_workflow_run_provenance(
    client: TestClient, session: Session, auth_headers: dict,
):
    """
    Create a QCRecord with workflow_run_id (provenance link).
    Verify it appears in both the create response and GET.
    """
    wr_id = _create_workflow_run(session)

    payload = {
        "project_id": "P-PROV-001",
        "workflow_run_id": wr_id,
        "metadata": {"pipeline": "RNA-Seq"},
    }
    resp = client.post("/api/v1/qcmetrics", json=payload, headers=auth_headers)
    assert resp.status_code == 201

    data = resp.json()
    assert data["workflow_run_id"] == wr_id

    # GET should also show it
    get_resp = client.get(f"/api/v1/qcmetrics/{data['id']}")
    assert get_resp.status_code == 200
    assert get_resp.json()["workflow_run_id"] == wr_id


def test_create_qcrecord_without_workflow_run_id(
    client: TestClient, session: Session, auth_headers: dict,
):
    """
    Create a QCRecord without workflow_run_id — field should be null.
    Backward-compatible with existing callers.
    """
    payload = {
        "project_id": "P-PROV-002",
        "metadata": {"pipeline": "WGS"},
    }
    resp = client.post("/api/v1/qcmetrics", json=payload, headers=auth_headers)
    assert resp.status_code == 201
    assert resp.json()["workflow_run_id"] is None

    get_resp = client.get(f"/api/v1/qcmetrics/{resp.json()['id']}")
    assert get_resp.json()["workflow_run_id"] is None


def test_create_qcrecord_invalid_workflow_run_id(
    client: TestClient, session: Session, auth_headers: dict,
):
    """
    Providing a workflow_run_id that doesn't exist should return 422.
    """
    fake_uuid = str(uuid4())
    payload = {
        "project_id": "P-PROV-BAD",
        "workflow_run_id": fake_uuid,
        "metadata": {"pipeline": "WES"},
    }
    resp = client.post("/api/v1/qcmetrics", json=payload, headers=auth_headers)
    assert resp.status_code == 422
    assert "WorkflowRun not found" in resp.json()["detail"]


# ============================================================================
# Metric-level: sequencing_runs association
# ============================================================================


def test_create_metric_with_sequencing_run(
    client: TestClient, session: Session, auth_headers: dict,
):
    """
    Create a QCRecord with a metric scoped to a SequencingRun via direct FK.
    Verify the sequencing_run_id appears in the GET response.
    """
    sr_id = _create_sequencing_run(session)

    payload = {
        "project_id": "P-SR-001",
        "metadata": {"pipeline": "Demux"},
        "metrics": [
            {
                "name": "demux_stats",
                "sequencing_run_id": sr_id,
                "values": {
                    "total_clusters": 500000000,
                    "pct_q30": 92.5,
                },
            }
        ],
    }
    resp = client.post("/api/v1/qcmetrics", json=payload, headers=auth_headers)
    assert resp.status_code == 201

    get_resp = client.get(f"/api/v1/qcmetrics/{resp.json()['id']}")
    full = get_resp.json()

    metric = full["metrics"][0]
    assert metric["name"] == "demux_stats"
    assert metric["sequencing_run_id"] == sr_id

    # workflow_run_id should be null
    assert metric["workflow_run_id"] is None


def test_create_metric_with_workflow_run(
    client: TestClient, session: Session, auth_headers: dict,
):
    """
    Create a QCRecord with a metric scoped to a WorkflowRun via direct FK.
    Verify the workflow_run_id appears in the GET response.
    """
    wr_id = _create_workflow_run(session)

    payload = {
        "project_id": "P-WR-001",
        "metadata": {"pipeline": "RNA-Seq"},
        "metrics": [
            {
                "name": "execution_metrics",
                "workflow_run_id": wr_id,
                "values": {
                    "runtime_hours": 3.5,
                    "peak_memory_gb": 16,
                },
            }
        ],
    }
    resp = client.post("/api/v1/qcmetrics", json=payload, headers=auth_headers)
    assert resp.status_code == 201

    get_resp = client.get(f"/api/v1/qcmetrics/{resp.json()['id']}")
    full = get_resp.json()

    metric = full["metrics"][0]
    assert metric["name"] == "execution_metrics"
    assert metric["workflow_run_id"] == wr_id
    assert metric["sequencing_run_id"] is None


def test_create_metric_with_both_entities(
    client: TestClient, session: Session, auth_headers: dict,
):
    """
    Mixed scoping: a single metric scoped to both a SequencingRun
    and a WorkflowRun simultaneously via direct FKs.
    """
    sr_id = _create_sequencing_run(session)
    wr_id = _create_workflow_run(session)

    payload = {
        "project_id": "P-BOTH-001",
        "workflow_run_id": wr_id,
        "metadata": {"pipeline": "Demux"},
        "metrics": [
            {
                "name": "demux_qc",
                "sequencing_run_id": sr_id,
                "workflow_run_id": wr_id,
                "values": {
                    "lane_count": 8,
                },
            }
        ],
    }
    resp = client.post("/api/v1/qcmetrics", json=payload, headers=auth_headers)
    assert resp.status_code == 201

    get_resp = client.get(f"/api/v1/qcmetrics/{resp.json()['id']}")
    full = get_resp.json()

    assert full["workflow_run_id"] == wr_id

    metric = full["metrics"][0]
    assert metric["sequencing_run_id"] == sr_id
    assert metric["workflow_run_id"] == wr_id


def test_create_metric_with_samples_and_sequencing_run(
    client: TestClient, session: Session, auth_headers: dict,
):
    """
    Per-sample metrics scoped to a SequencingRun — e.g., per-sample demux yield.
    """
    sr_id = _create_sequencing_run(session)

    payload = {
        "project_id": "P-SR-SAMPLE-001",
        "metadata": {"pipeline": "Demux"},
        "metrics": [
            {
                "name": "sample_demux_yield",
                "samples": [{"sample_name": "SampleA"}],
                "sequencing_run_id": sr_id,
                "values": {
                    "reads": 25000000,
                    "pct_q30": 95.3,
                },
            }
        ],
    }
    resp = client.post("/api/v1/qcmetrics", json=payload, headers=auth_headers)
    assert resp.status_code == 201

    get_resp = client.get(f"/api/v1/qcmetrics/{resp.json()['id']}")
    metric = get_resp.json()["metrics"][0]
    assert len(metric["samples"]) == 1
    assert metric["samples"][0]["sample_name"] == "SampleA"
    assert metric["sequencing_run_id"] == sr_id


# ============================================================================
# FK validation errors for metric-level entities
# ============================================================================


def test_create_metric_invalid_sequencing_run_id(
    client: TestClient, session: Session, auth_headers: dict,
):
    """Invalid sequencing_run_id in a metric should return 422."""
    fake_uuid = str(uuid4())
    payload = {
        "project_id": "P-SR-BAD",
        "metadata": {"pipeline": "Demux"},
        "metrics": [
            {
                "name": "demux_stats",
                "sequencing_run_id": fake_uuid,
                "values": {"clusters": 100},
            }
        ],
    }
    resp = client.post("/api/v1/qcmetrics", json=payload, headers=auth_headers)
    assert resp.status_code == 422
    assert "SequencingRun not found" in resp.json()["detail"]


def test_create_metric_invalid_workflow_run_id(
    client: TestClient, session: Session, auth_headers: dict,
):
    """Invalid workflow_run_id in a metric should return 422."""
    fake_uuid = str(uuid4())
    payload = {
        "project_id": "P-WR-BAD",
        "metadata": {"pipeline": "RNA-Seq"},
        "metrics": [
            {
                "name": "execution_metrics",
                "workflow_run_id": fake_uuid,
                "values": {"runtime_hours": 1.0},
            }
        ],
    }
    resp = client.post("/api/v1/qcmetrics", json=payload, headers=auth_headers)
    assert resp.status_code == 422
    assert "WorkflowRun not found" in resp.json()["detail"]


# ============================================================================
# Search filtering
# ============================================================================


def test_search_by_workflow_run_id(
    client: TestClient, session: Session, auth_headers: dict,
):
    """
    GET /search?workflow_run_id=<uuid> should return only records
    with that provenance link on QCRecord.workflow_run_id.
    """
    wr_id = _create_workflow_run(session)

    # Create two records: one with provenance, one without
    client.post("/api/v1/qcmetrics", json={
        "project_id": "P-SEARCH-WR-1",
        "workflow_run_id": wr_id,
        "metadata": {"pipeline": "RNA-Seq"},
    }, headers=auth_headers)

    client.post("/api/v1/qcmetrics", json={
        "project_id": "P-SEARCH-WR-2",
        "metadata": {"pipeline": "WGS"},
    }, headers=auth_headers)

    # Search for the one with provenance
    resp = client.get(
        f"/api/v1/qcmetrics/search?workflow_run_id={wr_id}&latest=false"
    )
    assert resp.status_code == 200

    data = resp.json()
    assert data["total"] == 1
    assert data["data"][0]["project_id"] == "P-SEARCH-WR-1"
    assert data["data"][0]["workflow_run_id"] == wr_id


def test_search_by_sequencing_run_id(
    client: TestClient, session: Session, auth_headers: dict,
):
    """
    GET /search?sequencing_run_id=<uuid> should return records
    that have a metric scoped to that SequencingRun via direct FK.
    """
    sr_id = _create_sequencing_run(session)

    # Record with metric scoped to the sequencing run
    client.post("/api/v1/qcmetrics", json={
        "project_id": "P-SEARCH-SR-1",
        "metadata": {"pipeline": "Demux"},
        "metrics": [{
            "name": "demux_stats",
            "sequencing_run_id": sr_id,
            "values": {"clusters": 500000000},
        }],
    }, headers=auth_headers)

    # Record with no sequencing run associations
    client.post("/api/v1/qcmetrics", json={
        "project_id": "P-SEARCH-SR-2",
        "metadata": {"pipeline": "WES"},
    }, headers=auth_headers)

    resp = client.get(
        f"/api/v1/qcmetrics/search?sequencing_run_id={sr_id}&latest=false"
    )
    assert resp.status_code == 200

    data = resp.json()
    assert data["total"] == 1
    assert data["data"][0]["project_id"] == "P-SEARCH-SR-1"


# ============================================================================
# Backward compatibility of existing patterns
# ============================================================================


def test_existing_patterns_return_null_entity_fields(
    client: TestClient, session: Session, auth_headers: dict,
):
    """
    Records created without any entity scoping should return
    null/None for the new FK fields.
    """
    payload = {
        "project_id": "P-COMPAT-001",
        "metadata": {"pipeline": "RNA-Seq"},
        "metrics": [
            {
                "name": "alignment_stats",
                "samples": [{"sample_name": "Sample1"}],
                "values": {"reads": 50000000},
            }
        ],
    }
    resp = client.post("/api/v1/qcmetrics", json=payload, headers=auth_headers)
    assert resp.status_code == 201
    assert resp.json()["workflow_run_id"] is None

    get_resp = client.get(f"/api/v1/qcmetrics/{resp.json()['id']}")
    full = get_resp.json()
    assert full["workflow_run_id"] is None

    metric = full["metrics"][0]
    assert metric["sequencing_run_id"] is None
    assert metric["workflow_run_id"] is None
    # Existing fields still work
    assert len(metric["samples"]) == 1
    assert metric["samples"][0]["sample_name"] == "Sample1"


# ============================================================================
# Cascade deletes
# ============================================================================


def test_delete_qcrecord_cascades_entity_fks(
    client: TestClient, session: Session, auth_headers: dict,
):
    """
    Deleting a QCRecord should cascade-delete the QCMetric rows
    (including their entity FK references).
    """
    sr_id = _create_sequencing_run(session)
    wr_id = _create_workflow_run(session)

    create_resp = client.post("/api/v1/qcmetrics", json={
        "project_id": "P-CASCADE-001",
        "workflow_run_id": wr_id,
        "metadata": {"pipeline": "Demux"},
        "metrics": [{
            "name": "demux_stats",
            "sequencing_run_id": sr_id,
            "workflow_run_id": wr_id,
            "values": {"clusters": 100},
        }],
    }, headers=auth_headers)
    assert create_resp.status_code == 201
    qcrecord_id = create_resp.json()["id"]

    # Delete the record
    del_resp = client.delete(f"/api/v1/qcmetrics/{qcrecord_id}")
    assert del_resp.status_code == 200
    assert del_resp.json()["status"] == "deleted"

    # Verify it's gone
    get_resp = client.get(f"/api/v1/qcmetrics/{qcrecord_id}")
    assert get_resp.status_code == 404
