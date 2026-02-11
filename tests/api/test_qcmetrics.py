"""
Tests for the QCMetrics API.
"""

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session

from api.auth.models import User
from core.security import hash_password, create_access_token


@pytest.fixture(name="test_user")
def test_user_fixture(session: Session):
    """Create a test user for authentication."""
    user = User(
        email="testuser@example.com",
        username="test_user",
        hashed_password=hash_password("TestPassword123"),
        full_name="Test User",
        is_active=True,
        is_verified=True,
        is_superuser=False
    )
    session.add(user)
    session.commit()
    session.refresh(user)
    return user


@pytest.fixture(name="auth_headers")
def auth_headers_fixture(test_user: User):
    """Create authorization headers for the test user."""
    access_token = create_access_token(data={"sub": str(test_user.id)})
    return {"Authorization": f"Bearer {access_token}"}


def test_create_qcrecord_basic(client: TestClient, session: Session, auth_headers: dict):
    """
    Test creating a basic QC record with metadata only.

    Create returns minimal response; use GET to verify full data.
    """
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
    assert data["created_by"] == "test_user"
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
    """
    Test creating a QC record with single-sample metrics.
    """
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
    """
    Test creating a QC record with tumor/normal paired metrics.
    """
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
    """
    Test creating a QC record with workflow-level metrics (no samples).
    """
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


def test_create_qcrecord_with_output_files(client: TestClient, session: Session, auth_headers: dict):
    """
    Test creating a QC record with output files.
    """
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
    matrix_file = next(f for f in full_data["output_files"] if "matrix" in f["uri"])
    assert len(matrix_file["samples"]) == 0


def test_create_qcrecord_unauthorized(client: TestClient, session: Session):
    """
    Test that creating a QC record without authentication fails.
    """
    qcrecord_data = {
        "project_id": "P-TEST-UNAUTH",
        "metadata": {"pipeline": "RNA-Seq"}
    }

    response = client.post(
        "/api/v1/qcmetrics",
        json=qcrecord_data
    )
    assert response.status_code == 401


def test_search_qcrecords_empty(client: TestClient, session: Session):
    """
    Test searching QC records when none exist.
    """
    response = client.get("/api/v1/qcmetrics/search")
    assert response.status_code == 200

    data = response.json()
    assert data["total"] == 0
    assert data["data"] == []


def test_search_qcrecords_by_project_id(client: TestClient, session: Session, auth_headers: dict):
    """
    Test searching QC records by project ID.
    """
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


def test_search_qcrecords_latest_only(client: TestClient, session: Session, auth_headers: dict):
    """
    Test that latest=true returns only the newest record per project.
    """
    # Create two QC records for the same project
    qcrecord_data_1 = {
        "project_id": "P-LATEST-001",
        "metadata": {"version": "1.0"}
    }
    client.post("/api/v1/qcmetrics", json=qcrecord_data_1, headers=auth_headers)

    qcrecord_data_2 = {
        "project_id": "P-LATEST-001",
        "metadata": {"version": "2.0"}  # Different metadata, so not a duplicate
    }
    client.post("/api/v1/qcmetrics", json=qcrecord_data_2, headers=auth_headers)

    # Search with latest=true (default)
    response = client.get("/api/v1/qcmetrics/search?project_id=P-LATEST-001&latest=true")
    assert response.status_code == 200

    data = response.json()
    assert data["total"] == 1

    # Should be version 2.0 (the latest)
    metadata_dict = {m["key"]: m["value"] for m in data["data"][0]["metadata"]}
    assert metadata_dict["version"] == "2.0"


def test_search_qcrecords_all_versions(client: TestClient, session: Session, auth_headers: dict):
    """
    Test that latest=false returns all versions.
    """
    # Create two QC records for the same project
    qcrecord_data_1 = {
        "project_id": "P-ALLVER-001",
        "metadata": {"version": "1.0"}
    }
    client.post("/api/v1/qcmetrics", json=qcrecord_data_1, headers=auth_headers)

    qcrecord_data_2 = {
        "project_id": "P-ALLVER-001",
        "metadata": {"version": "2.0"}
    }
    client.post("/api/v1/qcmetrics", json=qcrecord_data_2, headers=auth_headers)

    # Search with latest=false
    response = client.get("/api/v1/qcmetrics/search?project_id=P-ALLVER-001&latest=false")
    assert response.status_code == 200

    data = response.json()
    assert data["total"] == 2


def test_search_qcrecords_post_with_metadata_filter(
    client: TestClient, session: Session, auth_headers: dict
):
    """
    Test POST search with metadata filtering.
    """
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


def test_get_qcrecord_by_id(client: TestClient, session: Session, auth_headers: dict):
    """
    Test getting a QC record by its ID.
    """
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
    """
    Test getting a non-existent QC record returns 404.
    """
    fake_uuid = "00000000-0000-0000-0000-000000000000"
    response = client.get(f"/api/v1/qcmetrics/{fake_uuid}")
    assert response.status_code == 404


def test_get_qcrecord_invalid_uuid(client: TestClient, session: Session):
    """
    Test getting with an invalid UUID format returns 400.
    """
    response = client.get("/api/v1/qcmetrics/not-a-uuid")
    assert response.status_code == 400


def test_delete_qcrecord(client: TestClient, session: Session, auth_headers: dict):
    """
    Test deleting a QC record.
    """
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
    """
    Test deleting a non-existent QC record returns 404.
    """
    fake_uuid = "00000000-0000-0000-0000-000000000000"
    response = client.delete(f"/api/v1/qcmetrics/{fake_uuid}")
    assert response.status_code == 404


def test_duplicate_detection(client: TestClient, session: Session, auth_headers: dict):
    """
    Test that equivalent records are detected as duplicates.
    """
    qcrecord_data = {
        "project_id": "P-DUP-001",
        "metadata": {"pipeline": "RNA-Seq", "version": "2.0"}
    }

    # Create first record
    response1 = client.post("/api/v1/qcmetrics", json=qcrecord_data, headers=auth_headers)
    assert response1.status_code == 201
    data1 = response1.json()
    assert data1["is_duplicate"] is False

    # Try to create identical record
    response2 = client.post("/api/v1/qcmetrics", json=qcrecord_data, headers=auth_headers)
    assert response2.status_code == 201
    data2 = response2.json()
    assert data2["is_duplicate"] is True

    # Should return the same record (duplicate detection)
    assert data1["id"] == data2["id"]


def test_numeric_metric_values(client: TestClient, session: Session, auth_headers: dict):
    """
    Test that numeric metric values (int, float) are accepted and returned
    with their original types preserved.

    This matches the legacy ES format where values like QC_ForwardReadCount=122483575
    were numeric rather than string.
    """
    qcrecord_data = {
        "project_id": "P-NUMERIC-001",
        "metadata": {"pipeline": "RNA-Seq"},
        "metrics": [
            {
                "name": "sample_qc_metrics",
                "samples": [{"sample_name": "SampleA"}],
                "values": {
                    "QC_ForwardReadCount": 122483575,  # int
                    "QC_ReverseReadCount": 122483575,  # int
                    "QC_FractionContaminatedReads": 0,  # int (zero)
                    "QC_MeanReadLength": 150,  # int
                    "QC_FractionReadsAligned": 0.587,  # float
                    "QC_StrandBalance": 0.5,  # float
                    "QC_Median5Bias": 0.395753,  # float
                    "QC_DynamicRange": 2452.4661796537  # float with high precision
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


def test_mixed_string_and_numeric_values(client: TestClient, session: Session, auth_headers: dict):
    """
    Test that both string and numeric values can be provided in the same metric,
    and each is returned with its original type.
    """
    qcrecord_data = {
        "project_id": "P-MIXED-001",
        "metadata": {"pipeline": "RNA-Seq"},
        "metrics": [
            {
                "name": "alignment_stats",
                "samples": [{"sample_name": "Sample1"}],
                "values": {
                    "total_reads": 50000000,  # numeric int
                    "alignment_rate": 97.5,  # numeric float
                    "reference_genome": "GRCh38",  # string
                    "status": "passed"  # string
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

    values_dict = {v["key"]: v["value"] for v in full_data["metrics"][0]["values"]}

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
