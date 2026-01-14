"""
Test /runs endpoint
"""

import datetime
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

import pytest
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
        "total_pages": 1,
        "current_page": 1,
        "per_page": 20,
        "has_next": False,
        "has_prev": False,
    }


# ============================
# Demultiplex Workflow Tests
# ============================

class TestDemuxAPI:
    """Test demux API endpoints"""

    def test_list_demux_workflows_empty(self, client: TestClient, mock_s3_client):
        """Test listing demux workflows when bucket is empty"""
        # Setup empty bucket
        mock_s3_client.setup_bucket("test-tool-configs-bucket", "", [], [])

        response = client.get("/api/v1/runs/demultiplex")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        assert len(data) == 0

    def test_list_demux_workflows_with_configs(self, client: TestClient, mock_s3_client):
        """Test listing demux workflows when multiple configs exist"""
        # Setup bucket with multiple workflow config files
        files = [
            {
                "Key": "bcl2fastq.yaml",
                "LastModified": "2024-01-01T12:00:00",
                "Size": 1024,
            },
            {
                "Key": "cellranger-mkfastq.yaml",
                "LastModified": "2024-01-02T12:00:00",
                "Size": 2048,
            },
            {
                "Key": "ontbasecalling.yml",
                "LastModified": "2024-01-03T12:00:00",
                "Size": 1536,
            },
            # Non-yaml files should be ignored
            {
                "Key": "README.md",
                "LastModified": "2024-01-04T12:00:00",
                "Size": 512,
            },
        ]
        mock_s3_client.setup_bucket("test-tool-configs-bucket", "", files, [])

        response = client.get("/api/v1/runs/demultiplex")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        assert len(data) == 3
        assert "bcl2fastq" in data
        assert "cellranger-mkfastq" in data
        assert "ontbasecalling" in data
        assert "README" not in data  # Non-yaml files excluded

    def test_get_demux_workflow_config_basic(self, client: TestClient, mock_s3_client):
        """Test retrieving a demux workflow config without aws_batch section"""
        # Create a basic workflow config without aws_batch
        tool_config_yaml = """
version: 1
workflow_id: bcl2fastq
workflow_name: BCL to FASTQ
workflow_description: Demultiplex Illumina Runs
inputs:
  - name: s3_run_folder_path
    desc: S3 Run Folder Path
    type: String
    required: true
  - name: command_line_options
    desc: Command-Line Options
    type: String
    default: --barcode-mismatches=1
  - name: assay_method
    desc: Assay Method
    type: Enum
    options:
      - RNA-Seq
      - WES
      - WGS
    required: true
help: Run Illumina bcl2fastq on an Illumina run
tags:
  - name: illumina_run
"""
        # Store in mock S3
        mock_s3_client.put_object(
            Bucket="test-tool-configs-bucket",
            Key="bcl2fastq.yaml",
            Body=tool_config_yaml.encode("utf-8"),
        )

        response = client.get("/api/v1/runs/demultiplex/bcl2fastq")
        assert response.status_code == 200
        data = response.json()

        assert data["version"] == 1
        assert data["workflow_id"] == "bcl2fastq"
        assert data["workflow_name"] == "BCL to FASTQ"
        assert data["workflow_description"] == "Demultiplex Illumina Runs"
        assert data["help"] == "Run Illumina bcl2fastq on an Illumina run"
        assert len(data["inputs"]) == 3
        assert len(data["tags"]) == 1
        assert data["tags"][0]["name"] == "illumina_run"
        # aws_batch should be None when not present
        assert data.get("aws_batch") is None

    def test_get_demux_workflow_config_with_aws_batch(self, client: TestClient, mock_s3_client):
        """Test retrieving a demux workflow config with aws_batch section"""
        # Create a workflow config WITH aws_batch
        tool_config_yaml = """
version: 1
workflow_id: cellranger-mkfastq
workflow_name: CellRanger mkfastq
workflow_description: Demultiplex Illumina run with CellRanger
inputs:
  - name: s3_run_folder_path
    desc: S3 Run Folder Path
    type: String
    required: true
  - name: barcode_mismatches
    desc: Barcode Mismatches
    type: Integer
    default: 1
help: Run cellranger mkfastq on an Illumina run
tags:
  - name: illumina_run
aws_batch:
  job_name: cellranger-mkfastq-test
  job_definition: ngs360-cellranger:11
  job_queue: cellRangerJobQueue-2fe9b27d39b85fa
  command: mkfastq.sh
  environment:
    - name: S3_RUNFOLDER_PATH
      value: "{{ s3_run_folder_path }}"
    - name: MKFASTQ_OPTS
      value: --barcode-mismatches={{ barcode_mismatches }}
    - name: USER
      value: "{{ user }}"
"""
        # Store in mock S3
        mock_s3_client.put_object(
            Bucket="test-tool-configs-bucket",
            Key="cellranger-mkfastq.yaml",
            Body=tool_config_yaml.encode("utf-8"),
        )

        response = client.get("/api/v1/runs/demultiplex/cellranger-mkfastq")
        assert response.status_code == 200
        data = response.json()

        assert data["version"] == 1
        assert data["workflow_id"] == "cellranger-mkfastq"
        assert data["workflow_name"] == "CellRanger mkfastq"

        # Verify aws_batch section is present and correct
        assert "aws_batch" in data
        assert data["aws_batch"] is not None
        aws_batch = data["aws_batch"]
        assert aws_batch["job_name"] == "cellranger-mkfastq-test"
        assert aws_batch["job_definition"] == "ngs360-cellranger:11"
        assert aws_batch["job_queue"] == "cellRangerJobQueue-2fe9b27d39b85fa"
        assert aws_batch["command"] == "mkfastq.sh"

        # Verify environment variables
        assert "environment" in aws_batch
        assert len(aws_batch["environment"]) == 3
        env_vars = {env["name"]: env["value"] for env in aws_batch["environment"]}
        assert "S3_RUNFOLDER_PATH" in env_vars
        assert env_vars["S3_RUNFOLDER_PATH"] == "{{ s3_run_folder_path }}"
        assert "MKFASTQ_OPTS" in env_vars
        assert env_vars["MKFASTQ_OPTS"] == "--barcode-mismatches={{ barcode_mismatches }}"
        assert "USER" in env_vars
        assert env_vars["USER"] == "{{ user }}"

    def test_get_demux_workflow_config_with_aws_batch_no_environment(
        self, client: TestClient, mock_s3_client
    ):
        """Test retrieving a demux workflow config with aws_batch but no environment section"""
        # Create a workflow config with minimal aws_batch (no environment vars)
        tool_config_yaml = """
version: 1
workflow_id: simple-tool
workflow_name: Simple Tool
workflow_description: A simple tool
inputs:
  - name: input_file
    desc: Input File
    type: String
    required: true
help: Simple tool help
tags:
  - name: basic
aws_batch:
  job_name: simple-job
  job_definition: simple-def:1
  job_queue: simple-queue
  command: run.sh
"""
        # Store in mock S3
        mock_s3_client.put_object(
            Bucket="test-tool-configs-bucket",
            Key="simple-tool.yaml",
            Body=tool_config_yaml.encode("utf-8"),
        )

        response = client.get("/api/v1/runs/demultiplex/simple-tool")
        assert response.status_code == 200
        data = response.json()

        # Verify aws_batch section is present but environment is None or empty
        assert "aws_batch" in data
        aws_batch = data["aws_batch"]
        assert aws_batch["job_name"] == "simple-job"
        assert aws_batch["command"] == "run.sh"
        # environment should be None or empty list
        assert aws_batch.get("environment") is None or aws_batch.get("environment") == []

    def test_get_demux_workflow_config_yml_extension(self, client: TestClient, mock_s3_client):
        """Test retrieving a demux workflow config with .yml extension (not .yaml)"""
        tool_config_yaml = """
version: 1
workflow_id: ont-tool
workflow_name: ONT Tool
workflow_description: Oxford Nanopore Tool
inputs:
  - name: input_path
    desc: Input Path
    type: String
    required: true
help: ONT basecalling
tags:
  - name: ont
"""
        # Store with .yml extension
        mock_s3_client.put_object(
            Bucket="test-tool-configs-bucket",
            Key="ont-tool.yml",
            Body=tool_config_yaml.encode("utf-8"),
        )

        response = client.get("/api/v1/runs/demultiplex/ont-tool")
        assert response.status_code == 200
        data = response.json()
        assert data["workflow_id"] == "ont-tool"

    def test_get_demux_workflow_config_not_found(self, client: TestClient, mock_s3_client):
        """Test retrieving a non-existent demux workflow config"""
        response = client.get("/api/v1/runs/demultiplex/nonexistent-tool")
        assert response.status_code == 404
        assert "not found" in response.json()["detail"].lower()

    def test_get_demux_workflow_config_invalid_yaml(self, client: TestClient, mock_s3_client):
        """Test retrieving a demux workflow config with invalid YAML"""
        # Use YAML with unclosed bracket to ensure parse error
        invalid_yaml = """
version: 1
workflow_id: broken-tool
inputs: [
  missing closing bracket
"""
        mock_s3_client.put_object(
            Bucket="test-tool-configs-bucket",
            Key="broken-tool.yaml",
            Body=invalid_yaml.encode("utf-8"),
        )

        response = client.get("/api/v1/runs/demultiplex/broken-tool")
        assert response.status_code == 422
        assert "yaml" in response.json()["detail"].lower()

    def test_list_demux_workflows_s3_error_no_credentials(
        self, client: TestClient, mock_s3_client
    ):
        """Test list demux workflows when AWS credentials are missing"""
        mock_s3_client.simulate_error("NoCredentialsError")

        response = client.get("/api/v1/runs/demultiplex")
        assert response.status_code == 401
        assert "credentials" in response.json()["detail"].lower()

    def test_list_demux_workflows_s3_error_no_bucket(
        self, client: TestClient, mock_s3_client
    ):
        """Test list demux workflows when S3 bucket doesn't exist"""
        mock_s3_client.simulate_error("NoSuchBucket")

        response = client.get("/api/v1/runs/demultiplex")
        assert response.status_code == 404
        assert "bucket" in response.json()["detail"].lower()

    def test_list_demux_workflows_s3_error_access_denied(
        self, client: TestClient, mock_s3_client
    ):
        """Test list demux workflows when access is denied"""
        mock_s3_client.simulate_error("AccessDenied")

        response = client.get("/api/v1/runs/demultiplex")
        assert response.status_code == 403
        assert "denied" in response.json()["detail"].lower()

    def test_get_demux_workflow_config_s3_error_no_credentials(
        self, client: TestClient, mock_s3_client
    ):
        """Test get demux workflow config when AWS credentials are missing"""
        mock_s3_client.simulate_error("NoCredentialsError")

        response = client.get("/api/v1/runs/demultiplex/some-tool")
        assert response.status_code == 401
        assert "credentials" in response.json()["detail"].lower()


class TestDemuxWorkflowConfigModels:
    """Test Pydantic models for workflow configs"""

    def test_demux_workflow_config_input_enum_requires_options(self):
        """Test that Enum input type requires options"""
        from pydantic import ValidationError
        from api.runs.models import DemuxWorkflowConfigInput, InputType

        # This should fail - Enum without options
        with pytest.raises(ValidationError) as exc_info:
            DemuxWorkflowConfigInput(
                name="assay",
                desc="Assay Type",
                type=InputType.ENUM,
                required=True,
            )

        # Verify the error mentions options
        assert "options" in str(exc_info.value).lower()

    def test_demux_workflow_config_input_enum_with_options(self):
        """Test that Enum input type works with options"""
        from api.runs.models import DemuxWorkflowConfigInput, InputType

        input_config = DemuxWorkflowConfigInput(
            name="assay",
            desc="Assay Type",
            type=InputType.ENUM,
            required=True,
            options=["RNA-Seq", "WES", "WGS"],
        )
        assert input_config.name == "assay"
        assert input_config.type == InputType.ENUM
        assert len(input_config.options) == 3

    def test_demux_workflow_config_input_string_type(self):
        """Test String input type doesn't require options"""
        from api.runs.models import DemuxWorkflowConfigInput, InputType

        input_config = DemuxWorkflowConfigInput(
            name="file_path",
            desc="File Path",
            type=InputType.STRING,
            required=True,
        )
        assert input_config.name == "file_path"
        assert input_config.type == InputType.STRING
        assert input_config.options is None

    def test_demux_workflow_config_input_integer_type(self):
        """Test Integer input type"""
        from api.runs.models import DemuxWorkflowConfigInput, InputType

        input_config = DemuxWorkflowConfigInput(
            name="threads",
            desc="Number of threads",
            type=InputType.INTEGER,
            default=4,
        )
        assert input_config.name == "threads"
        assert input_config.type == InputType.INTEGER
        assert input_config.default == 4

    def test_demux_workflow_config_input_boolean_type(self):
        """Test Boolean input type"""
        from api.runs.models import DemuxWorkflowConfigInput, InputType

        input_config = DemuxWorkflowConfigInput(
            name="verbose",
            desc="Verbose output",
            type=InputType.BOOLEAN,
            default=False,
        )
        assert input_config.name == "verbose"
        assert input_config.type == InputType.BOOLEAN
        assert input_config.default is False

    def test_demux_workflow_config_complete_with_aws_batch(self):
        """Test complete DemuxWorkflowConfig with aws_batch"""
        from api.jobs.models import AwsBatchEnvironment, AwsBatchConfig
        from api.runs.models import (
            DemuxWorkflowConfig,
            DemuxWorkflowConfigInput,
            DemuxWorkflowTag,
            InputType
        )

        tool_config = DemuxWorkflowConfig(
            version=1,
            workflow_id="test-tool",
            workflow_name="Test Tool",
            workflow_description="A test tool",
            inputs=[
                DemuxWorkflowConfigInput(
                    name="input1",
                    desc="Input 1",
                    type=InputType.STRING,
                    required=True,
                )
            ],
            help="Help text",
            tags=[DemuxWorkflowTag(name="test")],
            aws_batch=AwsBatchConfig(
                job_name="test-job",
                job_definition="test-def:1",
                job_queue="test-queue",
                command="run.sh",
                environment=[
                    AwsBatchEnvironment(name="VAR1", value="value1")
                ],
            ),
        )

        assert tool_config.version == 1
        assert tool_config.workflow_id == "test-tool"
        assert tool_config.aws_batch is not None
        assert tool_config.aws_batch.job_name == "test-job"
        assert len(tool_config.aws_batch.environment) == 1

    def test_demux_workflow_config_without_aws_batch(self):
        """Test DemuxWorkflowConfig without aws_batch (should be None)"""
        from api.runs.models import (
            DemuxWorkflowConfig,
            DemuxWorkflowConfigInput,
            DemuxWorkflowTag,
            InputType
        )

        tool_config = DemuxWorkflowConfig(
            version=1,
            workflow_id="test-tool",
            workflow_name="Test Tool",
            workflow_description="A test tool",
            inputs=[
                DemuxWorkflowConfigInput(
                    name="input1",
                    desc="Input 1",
                    type=InputType.STRING,
                    required=True,
                )
            ],
            help="Help text",
            tags=[DemuxWorkflowTag(name="test")],
        )

        assert tool_config.version == 1
        assert tool_config.workflow_id == "test-tool"
        assert tool_config.aws_batch is None


class TestSubmitJobEndpoint:
    """Test the submit job endpoint and related services"""

    def test_submit_job_success(
        self, client: TestClient, mock_s3_client, monkeypatch
    ):
        """Test successful job submission"""
        # Setup workflow config with aws_batch
        tool_config_yaml = """
version: 1
workflow_id: cellranger-mkfastq
workflow_name: CellRanger mkfastq
workflow_description: Demultiplex Illumina run with CellRanger
inputs:
  - name: s3_run_folder_path
    desc: S3 Run Folder Path
    type: String
    required: true
  - name: barcode_mismatches
    desc: Barcode Mismatches
    type: Integer
    default: 1
  - name: user
    desc: User
    type: String
    required: true
help: Run cellranger mkfastq on an Illumina run
tags:
  - name: illumina_run
aws_batch:
  job_name: cellranger-mkfastq-{{ s3_run_folder_path.split('/')[-1] }}
  job_definition: ngs360-cellranger:11
  job_queue: cellRangerJobQueue-2fe9b27d39b85fa
  command: mkfastq.sh
  environment:
    - name: S3_RUNFOLDER_PATH
      value: "{{ s3_run_folder_path }}"
    - name: MKFASTQ_OPTS
      value: --barcode-mismatches={{ barcode_mismatches }}
    - name: USER
      value: "{{ user }}"
"""
        mock_s3_client.put_object(
            Bucket="test-tool-configs-bucket",
            Key="cellranger-mkfastq.yaml",
            Body=tool_config_yaml.encode("utf-8"),
        )

        # Mock boto3 batch client
        mock_batch_response = {
            "jobId": "test-job-123",
            "jobName": "cellranger-mkfastq-test-run",
        }

        class MockBatchClient:
            def submit_job(self, **kwargs):
                return mock_batch_response

        def mock_boto3_client(service_name, region_name=None):
            if service_name == "batch":
                return MockBatchClient()
            return None

        monkeypatch.setattr("boto3.client", mock_boto3_client)

        # Submit job
        request_body = {
            "workflow_id": "cellranger-mkfastq",
            "run_barcode": "190110_MACHINE123_0001_FLOWCELL123",
            "inputs": {
                "s3_run_folder_path": "s3://bucket/test-run",
                "barcode_mismatches": 1,
                "user": "testuser",
            },
        }

        response = client.post(
            "/api/v1/runs/demultiplex", json=request_body
        )

        assert response.status_code == 200
        data = response.json()
        assert data["aws_job_id"] == "test-job-123"
        assert data["name"] == "cellranger-mkfastq-test-run"
        assert "command" in data
        assert data["command"] == "mkfastq.sh"
        assert "id" in data
        assert "status" in data
        assert data["user"] == "system"

    def test_submit_job_with_jinja_expressions(
        self, client: TestClient, mock_s3_client, monkeypatch
    ):
        """Test job submission with Jinja2 expressions in template"""
        tool_config_yaml = """
version: 1
workflow_id: test-tool
workflow_name: Test Tool
workflow_description: Test tool with Jinja expressions
inputs:
  - name: s3_path
    desc: S3 Path
    type: String
    required: true
  - name: max_reads
    desc: Max Reads
    type: Integer
    default: 1000
help: Test tool
tags:
  - name: test
aws_batch:
  job_name: test-{{ s3_path.split('/')[-1] }}-{{ max_reads }}
  job_definition: test-def:1
  job_queue: test-queue
  command: run.sh {{ max_reads }}
  environment:
    - name: S3_PATH
      value: "{{ s3_path }}"
    - name: MAX_READS
      value: "{{ max_reads }}"
"""
        mock_s3_client.put_object(
            Bucket="test-tool-configs-bucket",
            Key="test-tool.yaml",
            Body=tool_config_yaml.encode("utf-8"),
        )

        # Mock batch client
        captured_submit_args = {}

        class MockBatchClient:
            def submit_job(self, **kwargs):
                captured_submit_args.update(kwargs)
                return {"jobId": "job-456", "jobName": kwargs["jobName"]}

        def mock_boto3_client(service_name, region_name=None):
            if service_name == "batch":
                return MockBatchClient()
            return None

        monkeypatch.setattr("boto3.client", mock_boto3_client)

        request_body = {
            "workflow_id": "test-tool",
            "run_barcode": "test-run-123",
            "inputs": {
                "s3_path": "s3://bucket/folder/subfolder/file.txt",
                "max_reads": 5000,
            },
        }

        response = client.post("/api/v1/runs/demultiplex", json=request_body)

        assert response.status_code == 200
        data = response.json()

        # Verify Jinja2 expression was evaluated correctly
        assert data["name"] == "test-file.txt-5000"
        assert data["command"] == "run.sh 5000"
        assert data["aws_job_id"] == "job-456"
        assert data["user"] == "system"

        # Verify container overrides
        assert "containerOverrides" in captured_submit_args
        overrides = captured_submit_args["containerOverrides"]
        assert overrides["command"] == ["run.sh", "5000"]
        assert len(overrides["environment"]) == 2
        env_dict = {e["name"]: e["value"] for e in overrides["environment"]}
        assert env_dict["S3_PATH"] == "s3://bucket/folder/subfolder/file.txt"
        assert env_dict["MAX_READS"] == "5000"

    def test_submit_job_tool_not_found(
        self, client: TestClient, mock_s3_client
    ):
        """Test job submission when workflow config doesn't exist"""
        request_body = {
            "workflow_id": "non-existent-tool",
            "run_barcode": "test-run",
            "inputs": {"param": "value"},
        }

        response = client.post(
            "/api/v1/runs/demultiplex", json=request_body
        )

        assert response.status_code == 404
        data = response.json()
        assert "not found" in data["detail"].lower()

    def test_submit_job_no_aws_batch_config(
        self, client: TestClient, mock_s3_client
    ):
        """Test job submission when tool has no AWS Batch configuration"""
        tool_config_yaml = """
version: 1
workflow_id: no-batch-tool
workflow_name: No Batch Tool
workflow_description: Tool without AWS Batch config
inputs:
  - name: input1
    desc: Input 1
    type: String
    required: true
help: Help text
tags:
  - name: test
"""
        mock_s3_client.put_object(
            Bucket="test-tool-configs-bucket",
            Key="no-batch-tool.yaml",
            Body=tool_config_yaml.encode("utf-8"),
        )

        request_body = {
            "workflow_id": "no-batch-tool",
            "run_barcode": "test-run",
            "inputs": {"input1": "value1"},
        }

        response = client.post("/api/v1/runs/demultiplex", json=request_body)

        assert response.status_code == 400
        data = response.json()
        assert "not configured for AWS Batch" in data["detail"]

    def test_submit_job_batch_client_error(
        self, client: TestClient, mock_s3_client, monkeypatch
    ):
        """Test job submission when AWS Batch client raises an error"""
        tool_config_yaml = """
version: 1
workflow_id: batch-error-tool
workflow_name: Batch Error Tool
workflow_description: Tool that will cause batch error
inputs:
  - name: input1
    desc: Input 1
    type: String
    required: true
help: Help text
tags:
  - name: test
aws_batch:
  job_name: test-job
  job_definition: test-def:1
  job_queue: test-queue
  command: run.sh
"""
        mock_s3_client.put_object(
            Bucket="test-tool-configs-bucket",
            Key="batch-error-tool.yaml",
            Body=tool_config_yaml.encode("utf-8"),
        )

        # Mock batch client that raises error
        from botocore.exceptions import ClientError

        class MockBatchClient:
            def submit_job(self, **kwargs):
                raise ClientError(
                    {
                        "Error": {
                            "Code": "InvalidParameterValueException",
                            "Message": "Invalid job definition",
                        }
                    },
                    "SubmitJob",
                )

        def mock_boto3_client(service_name, region_name=None):
            if service_name == "batch":
                return MockBatchClient()
            return None

        monkeypatch.setattr("boto3.client", mock_boto3_client)

        request_body = {
            "workflow_id": "batch-error-tool",
            "run_barcode": "test-run",
            "inputs": {"input1": "value1"},
        }

        response = client.post(
            "/api/v1/runs/demultiplex", json=request_body
        )

        assert response.status_code == 500
        data = response.json()
        assert "Failed to submit job" in data["detail"]

    def test_submit_job_with_empty_environment(
        self, client: TestClient, mock_s3_client, monkeypatch
    ):
        """Test job submission with no environment variables"""
        tool_config_yaml = """
version: 1
workflow_id: no-env-tool
workflow_name: No Environment Tool
workflow_description: Tool with no environment vars
inputs:
  - name: input1
    desc: Input 1
    type: String
    required: true
help: Help text
tags:
  - name: test
aws_batch:
  job_name: no-env-job
  job_definition: test-def:1
  job_queue: test-queue
  command: run.sh
"""
        mock_s3_client.put_object(
            Bucket="test-tool-configs-bucket",
            Key="no-env-tool.yaml",
            Body=tool_config_yaml.encode("utf-8"),
        )

        captured_submit_args = {}

        class MockBatchClient:
            def submit_job(self, **kwargs):
                captured_submit_args.update(kwargs)
                return {"jobId": "job-789", "jobName": kwargs["jobName"]}

        def mock_boto3_client(service_name, region_name=None):
            if service_name == "batch":
                return MockBatchClient()
            return None

        monkeypatch.setattr("boto3.client", mock_boto3_client)

        request_body = {
            "workflow_id": "no-env-tool",
            "run_barcode": "test-run",
            "inputs": {"input1": "value1"},
        }

        response = client.post("/api/v1/runs/demultiplex", json=request_body)

        assert response.status_code == 200
        data = response.json()
        assert data["aws_job_id"] == "job-789"
        assert data["name"] == "no-env-job"
        assert data["user"] == "system"

        # Verify environment is empty list
        overrides = captured_submit_args["containerOverrides"]
        assert overrides["environment"] == []

    def test_submit_job_invalid_request_body(self, client: TestClient):
        """Test job submission with invalid request body"""
        # Missing required field 'inputs'
        invalid_body = {
            "workflow_id": "test-tool",
            "run_barcode": "test-run",
        }

        response = client.post("/api/v1/runs/demultiplex", json=invalid_body)

        assert response.status_code == 422  # Validation error

    def test_submit_job_with_complex_inputs(
        self, client: TestClient, mock_s3_client, monkeypatch
    ):
        """Test job submission with various input types"""
        tool_config_yaml = """
version: 1
workflow_id: complex-tool
workflow_name: Complex Tool
workflow_description: Tool with complex inputs
inputs:
  - name: string_input
    desc: String Input
    type: String
    required: true
  - name: int_input
    desc: Integer Input
    type: Integer
    required: true
  - name: bool_input
    desc: Boolean Input
    type: Boolean
    required: false
  - name: enum_input
    desc: Enum Input
    type: Enum
    options:
      - option1
      - option2
    required: true
help: Help text
tags:
  - name: test
aws_batch:
  job_name: complex-{{ string_input }}-{{ int_input }}
  job_definition: test-def:1
  job_queue: test-queue
  command: run.sh
  environment:
    - name: STRING_VAL
      value: "{{ string_input }}"
    - name: INT_VAL
      value: "{{ int_input }}"
    - name: BOOL_VAL
      value: "{{ bool_input }}"
    - name: ENUM_VAL
      value: "{{ enum_input }}"
"""
        mock_s3_client.put_object(
            Bucket="test-tool-configs-bucket",
            Key="complex-tool.yaml",
            Body=tool_config_yaml.encode("utf-8"),
        )

        captured_submit_args = {}

        class MockBatchClient:
            def submit_job(self, **kwargs):
                captured_submit_args.update(kwargs)
                return {"jobId": "job-complex", "jobName": kwargs["jobName"]}

        def mock_boto3_client(service_name, region_name=None):
            if service_name == "batch":
                return MockBatchClient()
            return None

        monkeypatch.setattr("boto3.client", mock_boto3_client)

        request_body = {
            "workflow_id": "complex-tool",
            "run_barcode": "test-run",
            "inputs": {
                "string_input": "test_string",
                "int_input": 42,
                "bool_input": True,
                "enum_input": "option2",
            },
        }

        response = client.post("/api/v1/runs/demultiplex", json=request_body)

        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "complex-test_string-42"
        assert data["aws_job_id"] == "job-complex"
        assert data["user"] == "system"

        # Verify environment variables have correct values
        overrides = captured_submit_args["containerOverrides"]
        env_dict = {e["name"]: e["value"] for e in overrides["environment"]}
        assert env_dict["STRING_VAL"] == "test_string"
        assert env_dict["INT_VAL"] == "42"
        assert env_dict["BOOL_VAL"] == "True"
        assert env_dict["ENUM_VAL"] == "option2"


class TestInterpolateFunction:
    """Test the interpolate helper function"""

    def test_interpolate_simple_substitution(self):
        """Test simple variable substitution"""
        from api.runs.services import interpolate

        template = "Hello {{ name }}"
        inputs = {"name": "World"}
        result = interpolate(template, inputs)
        assert result == "Hello World"

    def test_interpolate_multiple_variables(self):
        """Test multiple variable substitution"""
        from api.runs.services import interpolate

        template = "{{ greeting }} {{ name }}, you are {{ age }} years old"
        inputs = {"greeting": "Hello", "name": "Alice", "age": 30}
        result = interpolate(template, inputs)
        assert result == "Hello Alice, you are 30 years old"

    def test_interpolate_with_expression(self):
        """Test Jinja2 expressions"""
        from api.runs.services import interpolate

        template = "Last part: {{ path.split('/')[-1] }}"
        inputs = {"path": "s3://bucket/folder/file.txt"}
        result = interpolate(template, inputs)
        assert result == "Last part: file.txt"

    def test_interpolate_strips_whitespace(self):
        """Test that result is stripped of leading/trailing whitespace"""
        from api.runs.services import interpolate

        template = "  {{ value }}  "
        inputs = {"value": "test"}
        result = interpolate(template, inputs)
        assert result == "test"  # Whitespace stripped from rendered output

    def test_interpolate_with_missing_variable(self):
        """Test behavior when variable is missing"""
        from api.runs.services import interpolate

        template = "Hello {{ missing_var }}"
        inputs = {"name": "World"}

        # Jinja2 by default renders undefined variables as empty strings
        # in sandboxed mode
        result = interpolate(template, inputs)
        # The sandboxed environment should handle missing variables
        # gracefully
        assert "Hello" in result
