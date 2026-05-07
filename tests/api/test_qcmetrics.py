"""
Tests for the QCMetrics API.

Covers:
- Basic CRUD (create, get, search, delete)
- Single-sample, paired-sample, and workflow-level metrics
- Output files
- Numeric and mixed-type metric values
- Duplicate detection
- Project FK validation
- Multi-entity extension: QCRecord.workflow_run_id provenance,
  QCMetric.sequencing_run_id / workflow_run_id scoping,
  search filtering, null FK defaults, cascade deletes
- Run-scoped QCRecords (no project_id, scoped to sequencing run)
"""
from datetime import date
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlmodel import Session, select

from api.project.models import Project
from api.runs.models import SequencingRun


# ---------------------------------------------------------------------------
# Helpers — create prerequisite entities directly in DB
# ---------------------------------------------------------------------------


def _ensure_project(session: Session, project_id: str) -> None:
    """Create a Project record if it doesn't already exist."""
    existing = session.exec(
        select(Project).where(Project.project_id == project_id)
    ).first()
    if not existing:
        session.add(Project(project_id=project_id, name=f"Test {project_id}"))
        session.commit()


def _create_sequencing_run(session: Session) -> str:
    """Create a SequencingRun; return its run_id string."""
    flowcell_id = f"H{uuid4().hex[:8].upper()}"
    sr = SequencingRun(
        id=uuid4(),
        run_id=f"240615_M00001_0042_{flowcell_id}",
        run_date=date(2024, 6, 15),
        machine_id="M00001",
        run_number="42",
        flowcell_id=flowcell_id,
    )
    session.add(sr)
    session.flush()
    sr_run_id = sr.run_id
    session.commit()
    return sr_run_id


# ============================================================================
# Basic CRUD
# ============================================================================


def test_create_qcrecord_basic(client: TestClient, session: Session, auth_headers: dict):
    """Test that a basic QC record with metadata only is created correctly."""
    _ensure_project(session, "P-TEST-001")

    qcrecord_data = {
        "project_id": "P-TEST-001",
        "metadata": {
            "pipeline": "RNA-Seq",
            "version": "2.0.0"
        }
    }

    response = client.post(
        "/api/v1/qcmetrics",
        json=qcrecord_data,
        headers=auth_headers
    )
    assert response.status_code == 201

    # Check minimal create response
    data = response.json()
    assert data["project_id"] == "P-TEST-001"
    assert data["created_by"] == "testuser"
    assert data["is_duplicate"] is False
    assert "id" in data
    assert "created_on" in data

    # Verify full data via GET
    get_response = client.get(f"/api/v1/qcmetrics/{data['id']}")
    full_data = get_response.json()
    assert len(full_data["metadata"]) == 2

    # Check metadata values
    metadata_dict = {m["key"]: m["value"] for m in full_data["metadata"]}
    assert metadata_dict["pipeline"] == "RNA-Seq"
    assert metadata_dict["version"] == "2.0.0"


def test_create_qcrecord_with_single_sample_metrics(
    client: TestClient, session: Session, auth_headers: dict
):
    """Test that a QC record with single-sample metrics stores values and sample correctly."""
    _ensure_project(session, "P-TEST-002")

    qcrecord_data = {
        "project_id": "P-TEST-002",
        "metadata": {
            "pipeline": "WES"
        },
        "metrics": [
            {
                "name": "alignment_stats",
                "samples": [{"sample_name": "Sample1"}],
                "values": {
                    "total_reads": "50000000",
                    "mapped_reads": "48500000",
                    "alignment_rate": "97.0"
                }
            }
        ]
    }

    response = client.post(
        "/api/v1/qcmetrics",
        json=qcrecord_data,
        headers=auth_headers
    )
    assert response.status_code == 201

    # Verify via GET
    data = response.json()
    get_response = client.get(f"/api/v1/qcmetrics/{data['id']}")
    full_data = get_response.json()

    assert len(full_data["metrics"]) == 1

    metric = full_data["metrics"][0]
    assert metric["name"] == "alignment_stats"
    assert len(metric["samples"]) == 1
    assert metric["samples"][0]["sample_name"] == "Sample1"

    # Check metric values
    values_dict = {v["key"]: v["value"] for v in metric["values"]}
    assert values_dict["total_reads"] == "50000000"
    assert values_dict["alignment_rate"] == "97.0"


def test_create_qcrecord_with_paired_sample_metrics(
    client: TestClient, session: Session, auth_headers: dict
):
    """Test that a QC record with tumor/normal paired metrics preserves sample roles."""
    _ensure_project(session, "P-TEST-003")

    qcrecord_data = {
        "project_id": "P-TEST-003",
        "metadata": {
            "pipeline": "Somatic"
        },
        "metrics": [
            {
                "name": "somatic_variants",
                "samples": [
                    {"sample_name": "Sample1", "role": "tumor"},
                    {"sample_name": "Sample2", "role": "normal"}
                ],
                "values": {
                    "snv_count": "15234",
                    "indel_count": "1523",
                    "tmb": "8.5"
                }
            }
        ]
    }

    response = client.post(
        "/api/v1/qcmetrics",
        json=qcrecord_data,
        headers=auth_headers
    )
    assert response.status_code == 201

    # Verify via GET
    data = response.json()
    get_response = client.get(f"/api/v1/qcmetrics/{data['id']}")
    full_data = get_response.json()

    metric = full_data["metrics"][0]

    # Check paired samples with roles
    assert len(metric["samples"]) == 2
    samples_by_role = {s["role"]: s["sample_name"] for s in metric["samples"]}
    assert samples_by_role["tumor"] == "Sample1"
    assert samples_by_role["normal"] == "Sample2"


def test_create_qcrecord_with_workflow_level_metrics(
    client: TestClient, session: Session, auth_headers: dict
):
    """Test that a QC record with workflow-level metrics (no samples) stores values correctly."""
    _ensure_project(session, "P-TEST-004")

    qcrecord_data = {
        "project_id": "P-TEST-004",
        "metadata": {
            "pipeline": "RNA-Seq"
        },
        "metrics": [
            {
                "name": "pipeline_summary",
                "values": {
                    "total_samples_processed": "48",
                    "samples_passed_qc": "46",
                    "pipeline_runtime_hours": "12.5"
                }
            }
        ]
    }

    response = client.post(
        "/api/v1/qcmetrics",
        json=qcrecord_data,
        headers=auth_headers
    )
    assert response.status_code == 201

    # Verify via GET
    data = response.json()
    get_response = client.get(f"/api/v1/qcmetrics/{data['id']}")
    full_data = get_response.json()

    metric = full_data["metrics"][0]

    # Workflow-level metrics have no samples
    assert len(metric["samples"]) == 0

    values_dict = {v["key"]: v["value"] for v in metric["values"]}
    assert values_dict["total_samples_processed"] == "48"


def test_create_qcrecord_with_output_files(
    client: TestClient, session: Session, auth_headers: dict
):
    """Test that a QC record with output files stores file metadata, samples, hashes, and tags."""
    _ensure_project(session, "P-TEST-005")

    qcrecord_data = {
        "project_id": "P-TEST-005",
        "metadata": {
            "pipeline": "WGS"
        },
        "output_files": [
            {
                "uri": "s3://bucket/Sample1.bam",
                "size": 123456789,
                "samples": [{"sample_name": "Sample1"}],
                "hashes": {"md5": "abc123def456"},
                "tags": {"type": "alignment", "format": "bam"}
            },
            {
                "uri": "s3://bucket/expression_matrix.tsv",
                "size": 5678901,
                "hashes": {"sha256": "xyz789"},
                "tags": {"type": "expression"}
            }
        ]
    }

    response = client.post(
        "/api/v1/qcmetrics",
        json=qcrecord_data,
        headers=auth_headers
    )
    assert response.status_code == 201

    # Verify via GET
    data = response.json()
    get_response = client.get(f"/api/v1/qcmetrics/{data['id']}")
    full_data = get_response.json()

    assert len(full_data["output_files"]) == 2

    # Check first file (single sample)
    bam_file = next(f for f in full_data["output_files"] if "bam" in f["uri"])
    assert bam_file["size"] == 123456789
    assert len(bam_file["samples"]) == 1
    assert bam_file["samples"][0]["sample_name"] == "Sample1"

    # Check hashes
    hashes_dict = {h["algorithm"]: h["value"] for h in bam_file["hashes"]}
    assert hashes_dict["md5"] == "abc123def456"

    # Check tags
    tags_dict = {t["key"]: t["value"] for t in bam_file["tags"]}
    assert tags_dict["type"] == "alignment"

    # Check second file (workflow-level, no samples)
    matrix_file = next(
        f for f in full_data["output_files"] if "matrix" in f["uri"]
    )
    assert len(matrix_file["samples"]) == 0


def test_create_qcrecord_unauthorized(
    unauthenticated_client: TestClient, session: Session
):
    """Test that creating a QC record without authentication returns 401."""
    qcrecord_data = {
        "project_id": "P-TEST-UNAUTH",
        "metadata": {"pipeline": "RNA-Seq"}
    }

    response = unauthenticated_client.post(
        "/api/v1/qcmetrics",
        json=qcrecord_data
    )
    assert response.status_code == 401


def test_create_qcrecord_nonexistent_project(
    client: TestClient, session: Session, auth_headers: dict
):
    """Test that creating a QC record with a non-existent project_id returns 422."""
    qcrecord_data = {
        "project_id": "P-DOES-NOT-EXIST",
        "metadata": {"pipeline": "RNA-Seq"}
    }

    response = client.post(
        "/api/v1/qcmetrics",
        json=qcrecord_data,
        headers=auth_headers
    )
    assert response.status_code == 422
    assert "Project not found" in response.json()["detail"]


# ============================================================================
# Search
# ============================================================================


def test_search_qcrecords_empty(client: TestClient, session: Session):
    """Test that searching QC records when none exist returns an empty list."""
    response = client.get("/api/v1/qcmetrics/search")
    assert response.status_code == 200

    data = response.json()
    assert data["total"] == 0
    assert data["data"] == []


def test_search_qcrecords_by_project_id(
    client: TestClient, session: Session, auth_headers: dict
):
    """Test that searching QC records by project_id returns matching records."""
    _ensure_project(session, "P-SEARCH-001")

    # Create a QC record
    qcrecord_data = {
        "project_id": "P-SEARCH-001",
        "metadata": {"pipeline": "RNA-Seq"}
    }
    client.post("/api/v1/qcmetrics", json=qcrecord_data, headers=auth_headers)

    # Search for it
    response = client.get("/api/v1/qcmetrics/search?project_id=P-SEARCH-001")
    assert response.status_code == 200

    data = response.json()
    assert data["total"] == 1
    assert data["data"][0]["project_id"] == "P-SEARCH-001"


def test_search_qcrecords_latest_only(
    client: TestClient, session: Session, auth_headers: dict
):
    """Test that latest=true returns only the newest record per project."""
    _ensure_project(session, "P-LATEST-001")

    # Create two QC records for the same project
    qcrecord_data_1 = {
        "project_id": "P-LATEST-001",
        "metadata": {"version": "1.0"}
    }
    client.post(
        "/api/v1/qcmetrics", json=qcrecord_data_1, headers=auth_headers
    )

    qcrecord_data_2 = {
        "project_id": "P-LATEST-001",
        "metadata": {"version": "2.0"}  # Different metadata, so not a duplicate
    }
    client.post(
        "/api/v1/qcmetrics", json=qcrecord_data_2, headers=auth_headers
    )

    # Search with latest=true (default)
    response = client.get(
        "/api/v1/qcmetrics/search?project_id=P-LATEST-001&latest=true"
    )
    assert response.status_code == 200

    data = response.json()
    assert data["total"] == 1

    # Should be version 2.0 (the latest)
    metadata_dict = {
        m["key"]: m["value"] for m in data["data"][0]["metadata"]
    }
    assert metadata_dict["version"] == "2.0"


def test_search_qcrecords_all_versions(
    client: TestClient, session: Session, auth_headers: dict
):
    """Test that latest=false returns all record versions for a project."""
    _ensure_project(session, "P-ALLVER-001")

    # Create two QC records for the same project
    qcrecord_data_1 = {
        "project_id": "P-ALLVER-001",
        "metadata": {"version": "1.0"}
    }
    client.post(
        "/api/v1/qcmetrics", json=qcrecord_data_1, headers=auth_headers
    )

    qcrecord_data_2 = {
        "project_id": "P-ALLVER-001",
        "metadata": {"version": "2.0"}
    }
    client.post(
        "/api/v1/qcmetrics", json=qcrecord_data_2, headers=auth_headers
    )

    # Search with latest=false
    response = client.get(
        "/api/v1/qcmetrics/search?project_id=P-ALLVER-001&latest=false"
    )
    assert response.status_code == 200

    data = response.json()
    assert data["total"] == 2


def test_search_qcrecords_post_with_metadata_filter(
    client: TestClient, session: Session, auth_headers: dict
):
    """Test that POST search with metadata filter returns only matching records."""
    _ensure_project(session, "P-META-001")
    _ensure_project(session, "P-META-002")

    # Create QC records with different pipelines
    client.post("/api/v1/qcmetrics", json={
        "project_id": "P-META-001",
        "metadata": {"pipeline": "RNA-Seq"}
    }, headers=auth_headers)
    client.post("/api/v1/qcmetrics", json={
        "project_id": "P-META-002",
        "metadata": {"pipeline": "WES"}
    }, headers=auth_headers)

    # Search for RNA-Seq pipeline only
    search_request = {
        "filter_on": {
            "metadata": {"pipeline": "RNA-Seq"}
        }
    }
    response = client.post("/api/v1/qcmetrics/search", json=search_request)
    assert response.status_code == 200

    data = response.json()
    assert data["total"] == 1
    assert data["data"][0]["project_id"] == "P-META-001"


def test_search_by_workflow_run_id(
    client: TestClient, session: Session, auth_headers: dict,
):
    """
    GET /search?workflow_run_id=<uuid> should return only records
    with that provenance link on QCRecord.workflow_run_id.
    """
    wr_id = str(uuid4())
    _ensure_project(session, "P-SEARCH-WR-1")
    _ensure_project(session, "P-SEARCH-WR-2")

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
    """Test that GET /search?sequencing_run_id filters records whose metrics reference that run."""
    sr_run_id = _create_sequencing_run(session)
    _ensure_project(session, "P-SEARCH-SR-1")
    _ensure_project(session, "P-SEARCH-SR-2")

    # Record with metric scoped to the sequencing run
    client.post("/api/v1/qcmetrics", json={
        "project_id": "P-SEARCH-SR-1",
        "metadata": {"pipeline": "Demux"},
        "metrics": [{
            "name": "demux_stats",
            "sequencing_run_id": sr_run_id,
            "values": {"clusters": 500000000},
        }],
    }, headers=auth_headers)

    # Record with no sequencing run associations
    client.post("/api/v1/qcmetrics", json={
        "project_id": "P-SEARCH-SR-2",
        "metadata": {"pipeline": "WES"},
    }, headers=auth_headers)

    resp = client.get(
        f"/api/v1/qcmetrics/search?sequencing_run_id={sr_run_id}&latest=false"
    )
    assert resp.status_code == 200

    data = resp.json()
    assert data["total"] == 1
    assert data["data"][0]["project_id"] == "P-SEARCH-SR-1"


# ============================================================================
# Get / Delete
# ============================================================================


def test_get_qcrecord_by_id(
    client: TestClient, session: Session, auth_headers: dict
):
    """Test that a QC record can be retrieved by its ID with full metadata."""
    _ensure_project(session, "P-GET-001")

    # Create a QC record
    create_response = client.post("/api/v1/qcmetrics", json={
        "project_id": "P-GET-001",
        "metadata": {"pipeline": "RNA-Seq"}
    }, headers=auth_headers)
    qcrecord_id = create_response.json()["id"]

    # Get by ID
    response = client.get(f"/api/v1/qcmetrics/{qcrecord_id}")
    assert response.status_code == 200

    data = response.json()
    assert data["id"] == qcrecord_id
    assert data["project_id"] == "P-GET-001"

    # Full response should include metadata
    assert len(data["metadata"]) == 1
    assert data["metadata"][0]["key"] == "pipeline"


def test_get_qcrecord_not_found(client: TestClient, session: Session):
    """Test that getting a non-existent QC record returns 404."""
    fake_uuid = "00000000-0000-0000-0000-000000000000"
    response = client.get(f"/api/v1/qcmetrics/{fake_uuid}")
    assert response.status_code == 404


def test_get_qcrecord_invalid_uuid(client: TestClient, session: Session):
    """Test that getting a QC record with an invalid UUID format returns 400."""
    response = client.get("/api/v1/qcmetrics/not-a-uuid")
    assert response.status_code == 400


def test_delete_qcrecord(
    client: TestClient, session: Session, auth_headers: dict
):
    """Test that deleting a QC record removes it and subsequent GET returns 404."""
    _ensure_project(session, "P-DELETE-001")

    # Create a QC record
    create_response = client.post("/api/v1/qcmetrics", json={
        "project_id": "P-DELETE-001",
        "metadata": {"pipeline": "RNA-Seq"}
    }, headers=auth_headers)
    qcrecord_id = create_response.json()["id"]

    # Delete it
    response = client.delete(f"/api/v1/qcmetrics/{qcrecord_id}")
    assert response.status_code == 200
    assert response.json()["status"] == "deleted"

    # Verify it's gone
    get_response = client.get(f"/api/v1/qcmetrics/{qcrecord_id}")
    assert get_response.status_code == 404


def test_delete_qcrecord_not_found(client: TestClient, session: Session):
    """Test that deleting a non-existent QC record returns 404."""
    fake_uuid = "00000000-0000-0000-0000-000000000000"
    response = client.delete(f"/api/v1/qcmetrics/{fake_uuid}")
    assert response.status_code == 404


# ============================================================================
# Duplicate detection
# ============================================================================


def test_duplicate_detection(
    client: TestClient, session: Session, auth_headers: dict
):
    """Test that submitting an identical QC record returns is_duplicate=True and the same ID."""
    _ensure_project(session, "P-DUP-001")

    qcrecord_data = {
        "project_id": "P-DUP-001",
        "metadata": {"pipeline": "RNA-Seq", "version": "2.0"}
    }

    # Create first record
    response1 = client.post(
        "/api/v1/qcmetrics", json=qcrecord_data, headers=auth_headers
    )
    assert response1.status_code == 201
    data1 = response1.json()
    assert data1["is_duplicate"] is False

    # Try to create identical record
    response2 = client.post(
        "/api/v1/qcmetrics", json=qcrecord_data, headers=auth_headers
    )
    assert response2.status_code == 201
    data2 = response2.json()
    assert data2["is_duplicate"] is True

    # Should return the same record (duplicate detection)
    assert data1["id"] == data2["id"]


# ============================================================================
# Numeric and mixed-type metric values
# ============================================================================


def test_numeric_metric_values(
    client: TestClient, session: Session, auth_headers: dict
):
    """Test that numeric metric values (int, float) are accepted and returned with original types."""
    _ensure_project(session, "P-NUMERIC-001")

    qcrecord_data = {
        "project_id": "P-NUMERIC-001",
        "metadata": {"pipeline": "RNA-Seq"},
        "metrics": [
            {
                "name": "sample_qc_metrics",
                "samples": [{"sample_name": "SampleA"}],
                "values": {
                    "QC_ForwardReadCount": 122483575,
                    "QC_ReverseReadCount": 122483575,
                    "QC_FractionContaminatedReads": 0,
                    "QC_MeanReadLength": 150,
                    "QC_FractionReadsAligned": 0.587,
                    "QC_StrandBalance": 0.5,
                    "QC_Median5Bias": 0.395753,
                    "QC_DynamicRange": 2452.4661796537,
                }
            }
        ]
    }

    response = client.post(
        "/api/v1/qcmetrics",
        json=qcrecord_data,
        headers=auth_headers
    )
    assert response.status_code == 201

    # Verify via GET
    data = response.json()
    get_response = client.get(f"/api/v1/qcmetrics/{data['id']}")
    full_data = get_response.json()

    assert len(full_data["metrics"]) == 1

    metric = full_data["metrics"][0]
    assert metric["name"] == "sample_qc_metrics"
    assert len(metric["samples"]) == 1
    assert metric["samples"][0]["sample_name"] == "SampleA"

    # Values should be returned with their original types preserved
    values_dict = {v["key"]: v["value"] for v in metric["values"]}

    # Integer values
    assert values_dict["QC_ForwardReadCount"] == 122483575
    assert isinstance(values_dict["QC_ForwardReadCount"], int)
    assert values_dict["QC_FractionContaminatedReads"] == 0
    assert isinstance(values_dict["QC_FractionContaminatedReads"], int)
    assert values_dict["QC_MeanReadLength"] == 150
    assert isinstance(values_dict["QC_MeanReadLength"], int)

    # Float values
    assert values_dict["QC_FractionReadsAligned"] == 0.587
    assert isinstance(values_dict["QC_FractionReadsAligned"], float)
    assert values_dict["QC_DynamicRange"] == 2452.4661796537
    assert isinstance(values_dict["QC_DynamicRange"], float)


def test_mixed_string_and_numeric_values(
    client: TestClient, session: Session, auth_headers: dict
):
    """Test that string and numeric values coexist in the same metric with types preserved."""
    _ensure_project(session, "P-MIXED-001")

    qcrecord_data = {
        "project_id": "P-MIXED-001",
        "metadata": {"pipeline": "RNA-Seq"},
        "metrics": [
            {
                "name": "alignment_stats",
                "samples": [{"sample_name": "Sample1"}],
                "values": {
                    "total_reads": 50000000,
                    "alignment_rate": 97.5,
                    "reference_genome": "GRCh38",
                    "status": "passed",
                }
            }
        ]
    }

    response = client.post(
        "/api/v1/qcmetrics",
        json=qcrecord_data,
        headers=auth_headers
    )
    assert response.status_code == 201

    # Verify via GET
    data = response.json()
    get_response = client.get(f"/api/v1/qcmetrics/{data['id']}")
    full_data = get_response.json()

    values_dict = {
        v["key"]: v["value"] for v in full_data["metrics"][0]["values"]
    }

    # Numeric values returned with original types
    assert values_dict["total_reads"] == 50000000
    assert isinstance(values_dict["total_reads"], int)
    assert values_dict["alignment_rate"] == 97.5
    assert isinstance(values_dict["alignment_rate"], float)

    # String values remain as strings
    assert values_dict["reference_genome"] == "GRCh38"
    assert isinstance(values_dict["reference_genome"], str)
    assert values_dict["status"] == "passed"
    assert isinstance(values_dict["status"], str)


# ============================================================================
# Multi-entity: QCRecord.workflow_run_id provenance
# ============================================================================


def test_create_qcrecord_with_workflow_run_provenance(
    client: TestClient, session: Session, auth_headers: dict,
):
    """
    Create a QCRecord with workflow_run_id (provenance link).
    Verify it appears in both the create response and GET.
    """
    wr_id = str(uuid4())
    _ensure_project(session, "P-PROV-001")

    payload = {
        "project_id": "P-PROV-001",
        "workflow_run_id": wr_id,
        "metadata": {"pipeline": "RNA-Seq"},
    }
    resp = client.post(
        "/api/v1/qcmetrics", json=payload, headers=auth_headers
    )
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
    """Test that a QCRecord created without workflow_run_id has null for that field."""
    _ensure_project(session, "P-PROV-002")

    payload = {
        "project_id": "P-PROV-002",
        "metadata": {"pipeline": "WGS"},
    }
    resp = client.post(
        "/api/v1/qcmetrics", json=payload, headers=auth_headers
    )
    assert resp.status_code == 201
    assert resp.json()["workflow_run_id"] is None

    get_resp = client.get(f"/api/v1/qcmetrics/{resp.json()['id']}")
    assert get_resp.json()["workflow_run_id"] is None


def test_create_qcrecord_with_any_workflow_run_uuid(
    client: TestClient, session: Session, auth_headers: dict,
):
    """
    Any valid UUID is accepted for workflow_run_id (external DB reference).
    No FK validation — the UUID is a soft reference to an external system.
    """
    any_uuid = str(uuid4())
    _ensure_project(session, "P-PROV-ANY")

    payload = {
        "project_id": "P-PROV-ANY",
        "workflow_run_id": any_uuid,
        "metadata": {"pipeline": "WES"},
    }
    resp = client.post("/api/v1/qcmetrics", json=payload, headers=auth_headers)
    assert resp.status_code == 201
    assert resp.json()["workflow_run_id"] == any_uuid


# ============================================================================
# Multi-entity: QCMetric.sequencing_run_id / workflow_run_id scoping
# ============================================================================


def test_create_metric_with_sequencing_run(
    client: TestClient, session: Session, auth_headers: dict,
):
    """Test that a metric scoped to a SequencingRun returns the run_id in GET."""
    sr_run_id = _create_sequencing_run(session)
    _ensure_project(session, "P-SR-001")

    payload = {
        "project_id": "P-SR-001",
        "metadata": {"pipeline": "Demux"},
        "metrics": [
            {
                "name": "demux_stats",
                "sequencing_run_id": sr_run_id,
                "values": {
                    "total_clusters": 500000000,
                    "pct_q30": 92.5,
                },
            }
        ],
    }
    resp = client.post(
        "/api/v1/qcmetrics", json=payload, headers=auth_headers
    )
    assert resp.status_code == 201

    get_resp = client.get(f"/api/v1/qcmetrics/{resp.json()['id']}")
    full = get_resp.json()

    metric = full["metrics"][0]
    assert metric["name"] == "demux_stats"
    assert metric["sequencing_run_id"] == sr_run_id

    # workflow_run_id should be null
    assert metric["workflow_run_id"] is None


def test_create_metric_with_workflow_run(
    client: TestClient, session: Session, auth_headers: dict,
):
    """
    Create a QCRecord with a metric scoped to an external workflow run via UUID.
    Verify the workflow_run_id appears in the GET response.
    """
    wr_id = str(uuid4())
    _ensure_project(session, "P-WR-001")

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
    resp = client.post(
        "/api/v1/qcmetrics", json=payload, headers=auth_headers
    )
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
    and a workflow run simultaneously via run_id string + UUID.
    """
    sr_run_id = _create_sequencing_run(session)
    wr_id = str(uuid4())
    _ensure_project(session, "P-BOTH-001")

    payload = {
        "project_id": "P-BOTH-001",
        "workflow_run_id": wr_id,
        "metadata": {"pipeline": "Demux"},
        "metrics": [
            {
                "name": "demux_qc",
                "sequencing_run_id": sr_run_id,
                "workflow_run_id": wr_id,
                "values": {
                    "lane_count": 8,
                },
            }
        ],
    }
    resp = client.post(
        "/api/v1/qcmetrics", json=payload, headers=auth_headers
    )
    assert resp.status_code == 201

    get_resp = client.get(f"/api/v1/qcmetrics/{resp.json()['id']}")
    full = get_resp.json()

    assert full["workflow_run_id"] == wr_id

    metric = full["metrics"][0]
    assert metric["sequencing_run_id"] == sr_run_id
    assert metric["workflow_run_id"] == wr_id


def test_create_metric_with_samples_and_sequencing_run(
    client: TestClient, session: Session, auth_headers: dict,
):
    """Test that per-sample metrics scoped to a SequencingRun return both samples and run_id."""
    sr_run_id = _create_sequencing_run(session)
    _ensure_project(session, "P-SR-SAMPLE-001")

    payload = {
        "project_id": "P-SR-SAMPLE-001",
        "metadata": {"pipeline": "Demux"},
        "metrics": [
            {
                "name": "sample_demux_yield",
                "samples": [{"sample_name": "SampleA"}],
                "sequencing_run_id": sr_run_id,
                "values": {
                    "reads": 25000000,
                    "pct_q30": 95.3,
                },
            }
        ],
    }
    resp = client.post(
        "/api/v1/qcmetrics", json=payload, headers=auth_headers
    )
    assert resp.status_code == 201

    get_resp = client.get(f"/api/v1/qcmetrics/{resp.json()['id']}")
    metric = get_resp.json()["metrics"][0]
    assert len(metric["samples"]) == 1
    assert metric["samples"][0]["sample_name"] == "SampleA"
    assert metric["sequencing_run_id"] == sr_run_id


# ============================================================================
# Multi-entity: FK validation errors
# ============================================================================


def test_create_metric_invalid_sequencing_run_id(
    client: TestClient, session: Session, auth_headers: dict,
):
    """Test that a non-existent sequencing_run_id in a metric returns 422."""
    _ensure_project(session, "P-SR-BAD")

    payload = {
        "project_id": "P-SR-BAD",
        "metadata": {"pipeline": "Demux"},
        "metrics": [
            {
                "name": "demux_stats",
                "sequencing_run_id": "990101_FAKE_0001_NOFLOW",
                "values": {"clusters": 100},
            }
        ],
    }
    resp = client.post(
        "/api/v1/qcmetrics", json=payload, headers=auth_headers
    )
    assert resp.status_code == 422
    assert "SequencingRun not found" in resp.json()["detail"]


def test_create_metric_with_any_workflow_run_uuid(
    client: TestClient, session: Session, auth_headers: dict,
):
    """Any valid UUID is accepted for metric-level workflow_run_id (external DB reference)."""
    any_uuid = str(uuid4())
    _ensure_project(session, "P-WR-ANY")

    payload = {
        "project_id": "P-WR-ANY",
        "metadata": {"pipeline": "RNA-Seq"},
        "metrics": [
            {
                "name": "execution_metrics",
                "workflow_run_id": any_uuid,
                "values": {"runtime_hours": 1.0},
            }
        ],
    }
    resp = client.post("/api/v1/qcmetrics", json=payload, headers=auth_headers)
    assert resp.status_code == 201
    get_resp = client.get(f"/api/v1/qcmetrics/{resp.json()['id']}")
    assert get_resp.json()["metrics"][0]["workflow_run_id"] == any_uuid


# ============================================================================
# Multi-entity: null FK defaults
# ============================================================================


def test_existing_patterns_return_null_entity_fields(
    client: TestClient, session: Session, auth_headers: dict,
):
    """Test that records created without entity scoping return null for FK fields."""
    _ensure_project(session, "P-COMPAT-001")

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
    resp = client.post(
        "/api/v1/qcmetrics", json=payload, headers=auth_headers
    )
    assert resp.status_code == 201
    assert resp.json()["workflow_run_id"] is None

    get_resp = client.get(f"/api/v1/qcmetrics/{resp.json()['id']}")
    full = get_resp.json()
    assert full["workflow_run_id"] is None

    metric = full["metrics"][0]
    assert metric["sequencing_run_id"] is None
    assert metric["workflow_run_id"] is None
    assert len(metric["samples"]) == 1
    assert metric["samples"][0]["sample_name"] == "Sample1"


# ============================================================================
# Multi-entity: cascade deletes
# ============================================================================


def test_delete_qcrecord_cascades_entity_fks(
    client: TestClient, session: Session, auth_headers: dict,
):
    """
    Deleting a QCRecord should cascade-delete the QCMetric rows
    (including their entity FK references).
    """
    sr_run_id = _create_sequencing_run(session)
    wr_id = str(uuid4())
    _ensure_project(session, "P-CASCADE-001")

    create_resp = client.post("/api/v1/qcmetrics", json={
        "project_id": "P-CASCADE-001",
        "workflow_run_id": wr_id,
        "metadata": {"pipeline": "Demux"},
        "metrics": [{
            "name": "demux_stats",
            "sequencing_run_id": sr_run_id,
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


# ============================================================================
# Run-Scoped QCRecords
# ============================================================================


def test_create_run_scoped_qcrecord(
    client: TestClient, session: Session, auth_headers: dict,
):
    """Test that a QCRecord scoped to a sequencing run (no project_id) returns the run_id."""
    sr_run_id = _create_sequencing_run(session)

    payload = {
        "sequencing_run_id": sr_run_id,
        "metadata": {"pipeline": "bcl-convert", "version": "4.3"},
        "metrics": [{
            "name": "demux_summary",
            "values": {"total_reads": 800000000, "pf_reads": 750000000},
        }],
    }
    resp = client.post(
        "/api/v1/qcmetrics", json=payload, headers=auth_headers
    )
    assert resp.status_code == 201

    data = resp.json()
    assert data["project_id"] is None
    assert data["sequencing_run_id"] == sr_run_id
    assert data["is_duplicate"] is False

    # Verify full GET response
    get_resp = client.get(f"/api/v1/qcmetrics/{data['id']}")
    assert get_resp.status_code == 200
    full = get_resp.json()
    assert full["project_id"] is None
    assert full["sequencing_run_id"] == sr_run_id


def test_create_run_scoped_qcrecord_invalid_run_id(
    client: TestClient, session: Session, auth_headers: dict,
):
    """Test that a non-existent sequencing_run_id at record level returns 422."""
    payload = {
        "sequencing_run_id": "990101_FAKE_0001_NOFLOW",
        "metadata": {"pipeline": "bcl-convert"},
        "metrics": [{
            "name": "demux_summary",
            "values": {"total_reads": 100},
        }],
    }
    resp = client.post(
        "/api/v1/qcmetrics", json=payload, headers=auth_headers
    )
    assert resp.status_code == 422
    assert "SequencingRun not found" in resp.json()["detail"]


def test_create_qcrecord_no_scope(
    client: TestClient, session: Session, auth_headers: dict,
):
    """Test that omitting both project_id and sequencing_run_id returns a validation error."""
    payload = {
        "metadata": {"pipeline": "RNA-Seq"},
        "metrics": [{
            "name": "stats",
            "values": {"reads": 100},
        }],
    }
    resp = client.post(
        "/api/v1/qcmetrics", json=payload, headers=auth_headers
    )
    assert resp.status_code == 422


def test_create_qcrecord_both_scopes(
    client: TestClient, session: Session, auth_headers: dict,
):
    """Test that providing both project_id and sequencing_run_id returns a validation error."""
    sr_run_id = _create_sequencing_run(session)
    _ensure_project(session, "P-DUAL-001")

    payload = {
        "project_id": "P-DUAL-001",
        "sequencing_run_id": sr_run_id,
        "metadata": {"pipeline": "Demux"},
    }
    resp = client.post(
        "/api/v1/qcmetrics", json=payload, headers=auth_headers
    )
    assert resp.status_code == 422


def test_run_scoped_auto_propagation(
    client: TestClient, session: Session, auth_headers: dict,
):
    """Test that record-level sequencing_run_id auto-propagates to metrics that omit it."""
    sr_run_id = _create_sequencing_run(session)

    payload = {
        "sequencing_run_id": sr_run_id,
        "metadata": {"pipeline": "bcl-convert"},
        "metrics": [
            {
                "name": "lane1_stats",
                "values": {"reads": 200000000},
                # no sequencing_run_id -> inherited from record
            },
            {
                "name": "lane2_stats",
                "sequencing_run_id": sr_run_id,
                "values": {"reads": 300000000},
                # explicitly set -> should resolve the same
            },
        ],
    }
    resp = client.post(
        "/api/v1/qcmetrics", json=payload, headers=auth_headers
    )
    assert resp.status_code == 201

    get_resp = client.get(f"/api/v1/qcmetrics/{resp.json()['id']}")
    full = get_resp.json()

    # Both metrics should have the sequencing_run resolved
    for metric in full["metrics"]:
        assert metric["sequencing_run_id"] == sr_run_id


def test_search_by_sequencing_run_id_run_scoped(
    client: TestClient, session: Session, auth_headers: dict,
):
    """Test that GET /search?sequencing_run_id returns run-scoped records."""
    sr_run_id = _create_sequencing_run(session)

    # Create a run-scoped record
    client.post("/api/v1/qcmetrics", json={
        "sequencing_run_id": sr_run_id,
        "metadata": {"pipeline": "bcl-convert"},
        "metrics": [{
            "name": "demux",
            "values": {"reads": 100},
        }],
    }, headers=auth_headers)

    # Create a project-scoped record (should not match)
    _ensure_project(session, "P-UNRELATED-001")
    client.post("/api/v1/qcmetrics", json={
        "project_id": "P-UNRELATED-001",
        "metadata": {"pipeline": "WES"},
    }, headers=auth_headers)

    resp = client.get(
        f"/api/v1/qcmetrics/search?sequencing_run_id={sr_run_id}"
        "&latest=false"
    )
    assert resp.status_code == 200

    data = resp.json()
    assert data["total"] == 1
    assert data["data"][0]["sequencing_run_id"] == sr_run_id
    assert data["data"][0]["project_id"] is None


def test_run_scoped_duplicate_detection(
    client: TestClient, session: Session, auth_headers: dict,
):
    """Test that submitting the same run-scoped record twice returns is_duplicate=True."""
    sr_run_id = _create_sequencing_run(session)

    payload = {
        "sequencing_run_id": sr_run_id,
        "metadata": {"pipeline": "bcl-convert", "version": "4.3"},
        "metrics": [{
            "name": "demux",
            "values": {"reads": 500000000},
        }],
    }

    resp1 = client.post(
        "/api/v1/qcmetrics", json=payload, headers=auth_headers
    )
    assert resp1.status_code == 201
    assert resp1.json()["is_duplicate"] is False

    resp2 = client.post(
        "/api/v1/qcmetrics", json=payload, headers=auth_headers
    )
    assert resp2.status_code == 201
    assert resp2.json()["is_duplicate"] is True
    assert resp2.json()["id"] == resp1.json()["id"]


def test_run_scoped_latest_filter(
    client: TestClient, session: Session, auth_headers: dict,
):
    """Test that latest=true returns only the newest record per sequencing run."""
    sr_run_id = _create_sequencing_run(session)

    # Create first version
    client.post("/api/v1/qcmetrics", json={
        "sequencing_run_id": sr_run_id,
        "metadata": {"pipeline": "bcl-convert", "version": "4.2"},
        "metrics": [{
            "name": "demux", "values": {"reads": 100},
        }],
    }, headers=auth_headers)

    # Create second version (different metadata -> not a duplicate)
    client.post("/api/v1/qcmetrics", json={
        "sequencing_run_id": sr_run_id,
        "metadata": {"pipeline": "bcl-convert", "version": "4.3"},
        "metrics": [{
            "name": "demux", "values": {"reads": 200},
        }],
    }, headers=auth_headers)

    # latest=true should return only 1
    resp = client.get(
        f"/api/v1/qcmetrics/search?sequencing_run_id={sr_run_id}"
        "&latest=true"
    )
    assert resp.status_code == 200
    assert resp.json()["total"] == 1

    # latest=false should return both
    resp_all = client.get(
        f"/api/v1/qcmetrics/search?sequencing_run_id={sr_run_id}"
        "&latest=false"
    )
    assert resp_all.status_code == 200
    assert resp_all.json()["total"] == 2


def test_redemux_cleanup_deletes_run_scoped_qcrecords(
    client: TestClient, session: Session, auth_headers: dict,
):
    """Test that DELETE /runs/{run_id}/samples also deletes run-scoped QCRecords."""
    sr_run_id = _create_sequencing_run(session)

    # Create a run-scoped QCRecord
    create_resp = client.post("/api/v1/qcmetrics", json={
        "sequencing_run_id": sr_run_id,
        "metadata": {"pipeline": "bcl-convert"},
        "metrics": [{
            "name": "demux",
            "values": {"reads": 100},
        }],
    }, headers=auth_headers)
    assert create_resp.status_code == 201
    qcrecord_id = create_resp.json()["id"]

    # Verify it exists
    get_resp = client.get(f"/api/v1/qcmetrics/{qcrecord_id}")
    assert get_resp.status_code == 200

    # Clear samples (re-demux cleanup)
    clear_resp = client.delete(f"/api/v1/runs/{sr_run_id}/samples")
    assert clear_resp.status_code == 200
    assert clear_resp.json()["qcrecords_deleted"] == 1

    # QCRecord should be gone
    get_after = client.get(f"/api/v1/qcmetrics/{qcrecord_id}")
    assert get_after.status_code == 404
