"""
Test /runs endpoint
"""

import datetime
from pathlib import Path
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlmodel import Session

from api.runs.models import SequencingRun


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
        "status": "completed",
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
    assert data["status"] == "completed"
    assert data["barcode"] == "190110_MACHINE123_0001_FLOWCELL123"


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
        status="completed",
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
    assert data["data"][0]["status"] == "completed"
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
    assert data["status"] == "completed"
    assert data["barcode"] == "190110_MACHINE123_0001_FLOWCELL123"


def test_get_run_samplesheet(client: TestClient, session: Session):
    """Test that we can get a runs samplesheet"""

    # Read the test samplesheet file
    samplesheet_path = (
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
        run_folder_uri=samplesheet_path.as_posix(),
        status="completed",
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
    assert data["Summary"]["run_folder_uri"] == samplesheet_path.as_posix()
    assert data["Summary"]["status"] == "completed"
    assert data["Summary"]["barcode"] == run_barcode
    assert "id" not in data["Summary"]  # Database ID should not be exposed
