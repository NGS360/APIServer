"""
Test /runs endpoint
"""

import datetime
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

from botocore.exceptions import NoCredentialsError
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from api.runs.models import SequencingRun, RunStatus


def test_add_run(client: TestClient):
    """Test that we can add a run"""
    # Test No runs, this also ensure we are using the test db
    response = client.get("/api/v1/runs")
    assert response.status_code == 200
    assert response.json() == {
        "data": [],
        "total_items": 0,
        "total_pages": 0,
        "current_page": 1,
        "per_page": 20,
        "has_next": False,
        "has_prev": False,
    }

    # Add a run to the database
    new_run = {
        "run_date": "2019-01-10",
        "machine_id": "MACHINE123",
        "run_number": 1,
        "flowcell_id": "FLOWCELL123",
        "experiment_name": "Test Experiment",
        "run_folder_uri": "s3://bucket/path/to/run",
        "status": RunStatus.READY,
    }
    response = client.post("/api/v1/runs", json=new_run)
    assert response.status_code == 201
    data = response.json()
    assert data["run_date"] == "2019-01-10"
    assert data["machine_id"] == "MACHINE123"
    assert data["run_number"] == 1
    assert data["flowcell_id"] == "FLOWCELL123"
    assert data["experiment_name"] == "Test Experiment"
    assert data["run_folder_uri"] == "s3://bucket/path/to/run"
    assert data["status"] == RunStatus.READY.value
    assert data["barcode"] == "190110_MACHINE123_0001_FLOWCELL123"

    # Add a run with empty run_time string
    new_run = {
        "run_date": "2019-01-10",
        "machine_id": "MACHINE123",
        "run_number": 2,
        "flowcell_id": "FLOWCELL123",
        "experiment_name": "Test Experiment",
        "run_folder_uri": "s3://bucket/path/to/run",
        "status": RunStatus.READY,
        "run_time": "",
    }
    response = client.post("/api/v1/runs", json=new_run)
    assert response.status_code == 201
    data = response.json()
    assert data["run_time"] is None
    assert data["barcode"] == "190110_MACHINE123_0002_FLOWCELL123"

    # Try to add a run with an invalid run_time field
    new_run = {
        "run_date": "2019-01-10",
        "machine_id": "MACHINE123",
        "run_number": 3,
        "flowcell_id": "FLOWCELL123",
        "experiment_name": "Test Experiment",
        "run_folder_uri": "s3://bucket/path/to/run",
        "status": RunStatus.READY,
        "run_time": "invalid_time_format",
    }
    response = client.post("/api/v1/runs", json=new_run)
    assert response.status_code == 422

    # Add a run with valid run_time
    new_run = {
        "run_date": "2019-01-10",
        "machine_id": "MACHINE123",
        "run_number": 4,
        "flowcell_id": "FLOWCELL123",
        "experiment_name": "Test Experiment",
        "run_folder_uri": "s3://bucket/path/to/run",
        "status": RunStatus.READY,
        "run_time": "1230",
    }
    response = client.post("/api/v1/runs", json=new_run)
    assert response.status_code == 201

    # Add a run with an invalid run_time
    new_run = {
        "run_date": "2019-01-10",
        "machine_id": "MACHINE123",
        "run_number": 4,
        "flowcell_id": "FLOWCELL123",
        "experiment_name": "Test Experiment",
        "run_folder_uri": "s3://bucket/path/to/run",
        "status": RunStatus.READY,
        "run_time": "5678",
    }
    response = client.post("/api/v1/runs", json=new_run)
    assert response.status_code == 422


def test_get_runs(client: TestClient, session: Session):
    """Test that we can get all runs"""
    # Test No projects, this also ensure we are using the test db
    response = client.get("/api/v1/runs")
    assert response.status_code == 200
    assert response.json() == {
        "data": [],
        "total_items": 0,
        "total_pages": 0,
        "current_page": 1,
        "per_page": 20,
        "has_next": False,
        "has_prev": False,
    }

    # Add a run to the database
    new_run = SequencingRun(
        id=uuid4(),
        run_date=datetime.date(2019, 1, 10),
        machine_id="MACHINE123",
        run_number=1,
        flowcell_id="FLOWCELL123",
        experiment_name="Test Experiment",
        run_folder_uri="/dir/path/to/run",
        status=RunStatus.READY,
    )
    session.add(new_run)
    session.commit()

    # Test get runs again
    response = client.get("/api/v1/runs")
    assert response.status_code == 200
    data = response.json()
    assert data["total_items"] == 1
    assert data["data"][0]["machine_id"] == "MACHINE123"
    assert data["data"][0]["run_number"] == 1
    assert data["data"][0]["flowcell_id"] == "FLOWCELL123"
    assert data["data"][0]["experiment_name"] == "Test Experiment"
    assert data["data"][0]["run_folder_uri"] == "/dir/path/to/run"
    assert data["data"][0]["status"] == RunStatus.READY.value
    assert data["data"][0]["barcode"] == "190110_MACHINE123_0001_FLOWCELL123"

    # Test that we can get a specific run by ID
    run_barcode = "190110_MACHINE123_0001_FLOWCELL123"
    response = client.get(f"/api/v1/runs/{run_barcode}")
    assert response.status_code == 200
    data = response.json()
    assert data["run_date"] == "2019-01-10"
    assert data["machine_id"] == "MACHINE123"
    assert data["run_number"] == 1
    assert data["flowcell_id"] == "FLOWCELL123"
    assert data["experiment_name"] == "Test Experiment"
    assert data["run_folder_uri"] == "/dir/path/to/run"
    assert data["status"] == RunStatus.READY.value
    assert data["barcode"] == "190110_MACHINE123_0001_FLOWCELL123"


def test_get_run_samplesheet_invalid_run(client: TestClient):
    """Test that we get the correct response when the run does not exist"""
    run_barcode = "NONEXISTENT_RUN"
    response = client.get(f"/api/v1/runs/{run_barcode}/samplesheet")
    assert response.status_code == 404
    data = response.json()
    assert data["detail"] == f"Run with barcode {run_barcode} not found"


def test_get_run_samplesheet(client: TestClient, session: Session):
    """Test that we can get a runs samplesheet"""

    # Set the test run folder
    run_folder = (
        Path(__file__).parent.parent / "fixtures" / "190110_MACHINE123_0001_FLOWCELL123"
    )

    # Add a run to the database
    new_run = SequencingRun(
        id=uuid4(),
        run_date=datetime.date(2019, 1, 10),
        machine_id="MACHINE123",
        run_number=1,
        flowcell_id="FLOWCELL123",
        experiment_name="Test Experiment",
        run_folder_uri=run_folder.as_posix(),
        status=RunStatus.READY,
    )
    session.add(new_run)
    session.commit()

    # Test get samplesheet for the run
    run_barcode = "190110_MACHINE123_0001_FLOWCELL123"
    response = client.get(f"/api/v1/runs/{run_barcode}/samplesheet")
    assert response.status_code == 200
    data = response.json()
    assert data["Summary"]["run_date"] == "2019-01-10"
    assert data["Summary"]["machine_id"] == "MACHINE123"
    assert data["Summary"]["run_number"] == "1"
    assert data["Summary"]["run_time"] == ""
    assert data["Summary"]["flowcell_id"] == "FLOWCELL123"
    assert data["Summary"]["experiment_name"] == "Test Experiment"
    assert data["Summary"]["run_folder_uri"] == run_folder.as_posix()
    assert data["Summary"]["status"] == RunStatus.READY.value
    assert data["Summary"]["barcode"] == run_barcode
    assert "id" not in data["Summary"]  # Database ID should not be exposed


def test_get_run_samplesheet_no_result(client: TestClient, session: Session):
    """Test that we get the correct response when no samplesheet is available"""

    # Set the test run folder
    run_folder = (
        Path(__file__).parent.parent / "fixtures" / "190110_MACHINE123_0002_FLOWCELL123"
    )

    # Add a run to the database
    new_run = SequencingRun(
        id=uuid4(),
        run_date=datetime.date(2019, 1, 10),
        machine_id="MACHINE123",
        run_number=2,
        flowcell_id="FLOWCELL123",
        experiment_name="Test Experiment",
        run_folder_uri=run_folder.as_posix(),
        status=RunStatus.READY,
    )
    session.add(new_run)
    session.commit()

    # Test get samplesheet for the run
    run_barcode = "190110_MACHINE123_0002_FLOWCELL123"
    response = client.get(f"/api/v1/runs/{run_barcode}/samplesheet")
    assert response.status_code == 204


@patch('api.runs.services.IlluminaSampleSheet')
def test_get_run_samplesheet_no_s3_credentials(
    mock_sample_sheet, client: TestClient, session: Session
):
    """Test that we get the correct response when no AWS credentials are configured"""

    # Mock the SampleSheet to raise NoCredentialsError
    mock_sample_sheet.side_effect = NoCredentialsError()

    # Set the test run folder to an S3 path
    run_folder = "s3://bucket/path/to/run"

    # Add a run to the database
    new_run = SequencingRun(
        id=uuid4(),
        run_date=datetime.date(2019, 1, 10),
        machine_id="MACHINE123",
        run_number=1,
        flowcell_id="FLOWCELL123",
        experiment_name="Test Experiment",
        run_folder_uri=run_folder,
        status=RunStatus.READY,
    )
    session.add(new_run)
    session.commit()

    # Test get samplesheet for the run
    run_barcode = "190110_MACHINE123_0001_FLOWCELL123"
    response = client.get(f"/api/v1/runs/{run_barcode}/samplesheet")
    assert response.status_code == 500
    data = response.json()
    expected_detail = (
        "Error accessing samplesheet: "
        "botocore.exceptions.NoCredentialsError: Unable to locate credentials"
    )
    assert data["detail"] == expected_detail


def test_get_run_metrics_invalid_run(client: TestClient):
    """Test that we get the correct response when the run does not exist"""
    run_barcode = "NONEXISTENT_RUN"
    response = client.get(f"/api/v1/runs/{run_barcode}/metrics")
    assert response.status_code == 404
    data = response.json()
    assert data["detail"] == f"Run with barcode {run_barcode} not found"


def test_get_run_metrics(client: TestClient, session: Session):
    """Test that we can get a runs demux metrics"""

    # Set the test run folder
    run_folder = (
        Path(__file__).parent.parent / "fixtures" / "190110_MACHINE123_0001_FLOWCELL123"
    )

    # Add a run to the database
    new_run = SequencingRun(
        id=uuid4(),
        run_date=datetime.date(2019, 1, 10),
        machine_id="MACHINE123",
        run_number=1,
        flowcell_id="FLOWCELL123",
        experiment_name="Test Experiment",
        run_folder_uri=run_folder.as_posix(),
        status=RunStatus.READY,
    )
    session.add(new_run)
    session.commit()

    # Test get metrics for the run
    run_barcode = "190110_MACHINE123_0001_FLOWCELL123"
    response = client.get(f"/api/v1/runs/{run_barcode}/metrics")
    assert response.status_code == 200
    data = response.json()
    assert data["RunNumber"] == 1
    assert data["Flowcell"] == "FLOWCELL123"


def test_get_run_metrics_no_result(client: TestClient, session: Session):
    """Test that we can get a runs demux metrics"""

    # Set the test run folder
    run_folder = (
        Path(__file__).parent.parent / "fixtures" / "190110_MACHINE123_0002_FLOWCELL123"
    )

    # Add a run to the database
    new_run = SequencingRun(
        id=uuid4(),
        run_date=datetime.date(2019, 1, 10),
        machine_id="MACHINE123",
        run_number=2,
        flowcell_id="FLOWCELL123",
        experiment_name="Test Experiment",
        run_folder_uri=run_folder.as_posix(),
        status=RunStatus.READY,
    )
    session.add(new_run)
    session.commit()

    # Test get metrics for the run
    run_barcode = "190110_MACHINE123_0002_FLOWCELL123"
    response = client.get(f"/api/v1/runs/{run_barcode}/metrics")
    assert response.status_code == 204


def test_update_run_status(client: TestClient, session: Session):
    """Test that we can update a runs status"""

    # Add a run to the database
    new_run = SequencingRun(
        id=uuid4(),
        run_date=datetime.date(2019, 1, 10),
        machine_id="MACHINE123",
        run_number=1,
        flowcell_id="FLOWCELL123",
        experiment_name="Test Experiment",
        run_folder_uri="/dir/path/to/run",
        status=RunStatus.IN_PROGRESS,
    )
    session.add(new_run)
    session.commit()

    # Test update the run status
    run_barcode = "190110_MACHINE123_0001_FLOWCELL123"
    update_data = {"run_status": RunStatus.READY}
    response = client.put(f"/api/v1/runs/{run_barcode}", json=update_data)
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == RunStatus.READY.value
    assert data["barcode"] == "190110_MACHINE123_0001_FLOWCELL123"

    # Test that we can't specifiy an invalid status
    update_data = {"run_status": "INVALID_STATUS"}
    response = client.put(f"/api/v1/runs/{run_barcode}", json=update_data)
    assert response.status_code == 422


def test_upload_run_samplesheet(client: TestClient, session: Session, tmp_path: Path):
    """Test that we can upload a samplesheet for a run"""

    # Set the test run folder
    run_folder = tmp_path

    # Add a run to the database
    new_run = SequencingRun(
        id=uuid4(),
        run_date=datetime.date(2019, 1, 10),
        machine_id="MACHINE123",
        run_number=1,
        flowcell_id="FLOWCELL123",
        experiment_name="Test Experiment",
        run_folder_uri=run_folder.as_posix(),
        status=RunStatus.READY,
    )
    session.add(new_run)
    session.commit()

    # Upload the samplesheet via the API
    run_barcode = "190110_MACHINE123_0001_FLOWCELL123"

    with open("tests/fixtures/190110_MACHINE123_0001_FLOWCELL123/SampleSheet.csv", "rb") as f:
        files = {"file": ("SampleSheet.csv", f, "text/csv")}
        response = client.post(f"/api/v1/runs/{run_barcode}/samplesheet", files=files)
    assert response.status_code == 201


def test_get_demultiplex_workflows(client: TestClient, session: Session):
    """Test that we can get the available demultiplex workflows"""
    response = client.get("/api/v1/runs/demultiplex")
    assert response.status_code == 200
    data = response.json()
    assert "demux_analysis_name" in data
    assert isinstance(data["demux_analysis_name"], list)
    assert "bcl2fastq" in data["demux_analysis_name"]
    assert "cellranger" in data["demux_analysis_name"]


def test_post_demultiplex_analysis(client: TestClient, session):
    """Test that we can submit a demultiplex analysis request"""
    # Add a run to the database
    new_run = SequencingRun(
        id=uuid4(),
        run_date=datetime.date(2019, 1, 10),
        machine_id="MACHINE123",
        run_number=1,
        flowcell_id="FLOWCELL123",
        experiment_name="Test Experiment",
        run_folder_uri="/dir/path/to/run",
        status=RunStatus.READY,
    )
    session.add(new_run)
    session.commit()

    # Test submit a demultiplex analysis request
    run_barcode = "190110_MACHINE123_0001_FLOWCELL123"
    demux_data = {"demux_workflow": "bcl2fastq"}
    response = client.post(f"/api/v1/runs/demultiplex?run_barcode={run_barcode}", json=demux_data)
    assert response.status_code == 202


def test_search_runs(client: TestClient):
    """
    Run search that returns a SequencingRunsPublic model
    with sorting and pagination for rendering the table
    on the illumin_runs page.

    This is equivalent to the get runs endpoint, except that
    the searching and pagination is handled by OpenSearch, rather
    than handling pagination from the database.
    """
    # Add a run to the database
    new_run = {
        "run_date": "2019-01-10",
        "machine_id": "MACHINE123",
        "run_number": 1,
        "flowcell_id": "FLOWCELL123",
        "experiment_name": "Test Experiment AI",
        "run_folder_uri": "s3://bucket/path/to/run",
        "status": RunStatus.READY,
    }
    response = client.post("/api/v1/runs", json=new_run)
    assert response.status_code == 201

    # Test
    url = "/api/v1/runs/search"
    query_string = "query=AI&page=1&per_page=20&sort_by=barcode&sort_order=desc"
    response = client.get(f"{url}?{query_string}")

    assert response.status_code == 200
    assert response.json() == {
        "data": [
            {
                "barcode": "190110_MACHINE123_0001_FLOWCELL123",
                "run_date": "2019-01-10",
                "machine_id": "MACHINE123",
                "run_number": 1,
                "flowcell_id": "FLOWCELL123",
                "experiment_name": "Test Experiment AI",
                "run_folder_uri": "s3://bucket/path/to/run",
                "status": "Ready",
                "run_time": None,
            }
        ],
        "total_items": 1,
        "total_pages": 1,
        "current_page": 1,
        "per_page": 20,
        "has_next": False,
        "has_prev": False,
    }


def test_search_runs_db_opensearch_out_of_sync(client: TestClient, session: Session):
    """
    Test when the database and OpenSearch are out of sync.  OpenSearch will return
    a run that does not exist in the database.  Make sure the API handles this gracefully.
    """
    # Add a run
    new_run = {
        "run_date": "2019-01-10",
        "machine_id": "MACHINE123",
        "run_number": 1,
        "flowcell_id": "FLOWCELL123",
        "experiment_name": "Test Experiment AI",
        "run_folder_uri": "s3://bucket/path/to/run",
        "status": RunStatus.READY,
    }
    response = client.post("/api/v1/runs", json=new_run)
    assert response.status_code == 201

    # Flush to ensure data is written to the database
    session.flush()

    # Now delete from database to simulate out of sync
    run = session.exec(
        select(SequencingRun).where(
            SequencingRun.flowcell_id == 'FLOWCELL123',
        )
    ).first()
    session.delete(run)
    session.commit()

    # Test
    # OpenSearch will return the run, but the database will not have it
    url = "/api/v1/runs/search"
    query_string = "query=AI&page=1&per_page=20&sort_by=barcode&sort_order=desc"
    response = client.get(f"{url}?{query_string}")

    assert response.status_code == 200
    assert response.json() == {
        "data": [
        ],
        "total_items": 1,
        "total_pages": 0,
        "current_page": 1,
        "per_page": 20,
        "has_next": False,
        "has_prev": False,
    }
