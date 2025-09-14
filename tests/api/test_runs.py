"""
Test /runs endpoint
"""

import datetime
from uuid import uuid4
from unittest.mock import patch

import pytest
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
        # "s3_run_folder_path": "s3://bucket/path/to/run",
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
    # assert data["s3_run_folder_path"] == "s3://bucket/path/to/run"
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
        run_folder_uri="s3://bucket/path/to/run",
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
    assert data["data"][0]["run_folder_uri"] == "s3://bucket/path/to/run"
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
    assert data["run_folder_uri"] == "s3://bucket/path/to/run"
    assert data["status"] == "completed"
    assert data["barcode"] == "190110_MACHINE123_0001_FLOWCELL123"


def test_get_run_samplesheet(client: TestClient, session: Session):
    """Test that we can get a runs samplesheet"""
    # Add a run to the database
    new_run = SequencingRun(
        id=uuid4(),
        run_date=datetime.date(2019, 1, 10),
        machine_id="MACHINE123",
        run_number=1,
        flowcell_id="FLOWCELL123",
        experiment_name="Test Experiment",
        run_folder_uri="s3://bucket/path/to/run",
        status="completed",
    )
    session.add(new_run)
    session.commit()

    # Test get samplesheet for the run
    run_barcode = "190110_MACHINE123_0001_FLOWCELL123"
    response = client.get(f"/api/v1/runs/{run_barcode}/samplesheet")
    assert response.status_code == 200
    data = response.json()
    assert data['Summary']['run_date'] == '2019-01-10'
    assert data['Summary']['machine_id'] == 'MACHINE123'
    assert data['Summary']['run_number'] == '1'
    assert data['Summary']['run_time'] == ''
    assert data['Summary']['flowcell_id'] == 'FLOWCELL123'
    assert data['Summary']['experiment_name'] == 'Test Experiment'
    assert data['Summary']['run_folder_uri'] == 's3://bucket/path/to/run'
    assert data['Summary']['status'] == 'completed'
    assert data['Summary']['barcode'] == run_barcode
    assert 'id' not in data['Summary']  # Database ID should not be exposed


# ============================================================================
# Pytest Fixtures for Samplesheet Mocking (Strategy 2)
# ============================================================================


@pytest.fixture
def mock_illumina_samplesheet():
    """Fixture providing a complete Illumina samplesheet mock"""
    return {
        'Summary': {
            'run_date': '2019-01-10',
            'machine_id': 'MACHINE123',
            'run_number': '1',
            'run_time': '',
            'flowcell_id': 'FLOWCELL123',
            'experiment_name': 'Test Experiment',
            'run_folder_uri': 's3://bucket/path/to/run',
            'status': 'completed',
            'barcode': '190110_MACHINE123_0001_FLOWCELL123'
        },
        'Header': {
            'IEMFileVersion': '4',
            'Investigator Name': 'Jane Smith',
            'Experiment Name': 'Test Experiment',
            'Date': '1/10/2019',
            'Workflow': 'GenerateFASTQ',
            'Application': 'FASTQ Only',
            'Assay': 'TruSeq HT',
            'Description': 'Test sequencing run',
            'Chemistry': 'Amplicon'
        },
        'Reads': {
            'Read1': 151,
            'Read2': 151
        },
        'Settings': {
            'ReverseComplement': '0',
            'Adapter': 'AGATCGGAAGAGCACACGTCTGAACTCCAGTCA'
        },
        'DataCols': [
            'Sample_ID',
            'Sample_Name', 
            'Sample_Plate',
            'Sample_Well',
            'I7_Index_ID',
            'index',
            'I5_Index_ID',
            'index2',
            'Sample_Project',
            'Description'
        ],
        'Data': [
            {
                'Sample_ID': 'Sample_1',
                'Sample_Name': 'Sample_1',
                'Sample_Plate': '',
                'Sample_Well': '',
                'I7_Index_ID': 'N701',
                'index': 'TAAGGCGA',
                'I5_Index_ID': 'S501',
                'index2': 'TAGATCGC',
                'Sample_Project': 'TestProject',
                'Description': 'Test sample 1'
            },
            {
                'Sample_ID': 'Sample_2',
                'Sample_Name': 'Sample_2',
                'Sample_Plate': '',
                'Sample_Well': '',
                'I7_Index_ID': 'N702',
                'index': 'CGTACTAG',
                'I5_Index_ID': 'S502',
                'index2': 'CTCTCTAT',
                'Sample_Project': 'TestProject',
                'Description': 'Test sample 2'
            }
        ]
    }


@pytest.fixture
def mock_empty_samplesheet():
    """Fixture providing an empty samplesheet (when run not found)"""
    return {
        'Summary': {},
        'Header': {},
        'Reads': {},
        'Settings': {},
        'DataCols': [],
        'Data': []
    }


@pytest.fixture
def mock_single_sample_samplesheet():
    """Fixture providing a samplesheet with a single sample"""
    return {
        'Summary': {
            'run_date': '2019-01-10',
            'machine_id': 'MACHINE123',
            'run_number': '1',
            'flowcell_id': 'FLOWCELL123',
            'experiment_name': 'Single Sample Test',
            'status': 'completed',
            'barcode': '190110_MACHINE123_0001_FLOWCELL123'
        },
        'Header': {
            'IEMFileVersion': '4',
            'Investigator Name': 'John Doe',
            'Experiment Name': 'Single Sample Test'
        },
        'Reads': {
            'Read1': 151
        },
        'Settings': {
            'ReverseComplement': '0'
        },
        'DataCols': ['Sample_ID', 'Sample_Name', 'index', 'Sample_Project'],
        'Data': [
            {
                'Sample_ID': 'TestSample1',
                'Sample_Name': 'TestSample1',
                'index': 'TAAGGCGA',
                'Sample_Project': 'TestProject'
            }
        ]
    }


# ============================================================================
# Enhanced Tests using Strategy 1 (Service Layer Mocking) + Strategy 2 (Fixtures)
# ============================================================================

def test_get_run_samplesheet_with_full_mock(client: TestClient, mock_illumina_samplesheet):
    """Test samplesheet endpoint with a fully mocked samplesheet using fixtures"""
    
    # Mock the service function (Strategy 1)
    with patch('api.runs.services.get_run_samplesheet', return_value=mock_illumina_samplesheet):
        run_barcode = "190110_MACHINE123_0001_FLOWCELL123"
        response = client.get(f"/api/v1/runs/{run_barcode}/samplesheet")
        
        assert response.status_code == 200
        data = response.json()
        
        # Test Summary section
        assert data['Summary']['run_date'] == '2019-01-10'
        assert data['Summary']['machine_id'] == 'MACHINE123'
        assert data['Summary']['experiment_name'] == 'Test Experiment'
        assert data['Summary']['barcode'] == run_barcode
        assert 'id' not in data['Summary']  # Database ID should not be exposed
        
        # Test Header section
        assert data['Header']['Investigator Name'] == 'Jane Smith'
        assert data['Header']['Workflow'] == 'GenerateFASTQ'
        assert data['Header']['IEMFileVersion'] == '4'
        
        # Test Reads section
        assert data['Reads']['Read1'] == 151
        assert data['Reads']['Read2'] == 151
        
        # Test Settings section
        assert data['Settings']['ReverseComplement'] == '0'
        assert 'Adapter' in data['Settings']
        
        # Test Data section
        assert len(data['Data']) == 2
        assert data['Data'][0]['Sample_ID'] == 'Sample_1'
        assert data['Data'][0]['index'] == 'TAAGGCGA'
        assert data['Data'][1]['Sample_ID'] == 'Sample_2'
        assert data['Data'][1]['index'] == 'CGTACTAG'
        
        # Test DataCols section
        assert 'Sample_ID' in data['DataCols']
        assert 'index' in data['DataCols']
        assert 'Sample_Project' in data['DataCols']


def test_get_run_samplesheet_empty_response(client: TestClient, mock_empty_samplesheet):
    """Test samplesheet endpoint when run is not found"""
    
    with patch('api.runs.services.get_run_samplesheet', return_value=mock_empty_samplesheet):
        run_barcode = "999999_NOTFOUND_9999_MISSING999"
        response = client.get(f"/api/v1/runs/{run_barcode}/samplesheet")
        
        assert response.status_code == 200
        data = response.json()
        
        # Should return empty structure
        assert data['Summary'] == {}
        assert data['Header'] == {}
        assert data['Reads'] == {}
        assert data['Settings'] == {}
        assert data['DataCols'] == []
        assert data['Data'] == []


def test_get_run_samplesheet_single_sample(client: TestClient, mock_single_sample_samplesheet):
    """Test samplesheet endpoint with single sample"""
    
    with patch('api.runs.services.get_run_samplesheet', return_value=mock_single_sample_samplesheet):
        run_barcode = "190110_MACHINE123_0001_FLOWCELL123"
        response = client.get(f"/api/v1/runs/{run_barcode}/samplesheet")
        
        assert response.status_code == 200
        data = response.json()
        
        # Test Summary
        assert data['Summary']['experiment_name'] == 'Single Sample Test'
        
        # Test single sample in Data
        assert len(data['Data']) == 1
        assert data['Data'][0]['Sample_ID'] == 'TestSample1'
        assert data['Data'][0]['Sample_Project'] == 'TestProject'


@pytest.mark.parametrize("scenario,expected_samples,expected_experiment", [
    ("full_samplesheet", 2, "Test Experiment"),
    ("single_sample", 1, "Single Sample Test"),
    ("empty_samplesheet", 0, None)
])
def test_get_run_samplesheet_scenarios(
    client: TestClient,
    scenario,
    expected_samples,
    expected_experiment,
    mock_illumina_samplesheet,
    mock_single_sample_samplesheet,
    mock_empty_samplesheet
):
    """Test different samplesheet scenarios using parametrized tests"""
    
    # Select the appropriate fixture based on scenario
    if scenario == "full_samplesheet":
        mock_data = mock_illumina_samplesheet
    elif scenario == "single_sample":
        mock_data = mock_single_sample_samplesheet
    else:  # empty_samplesheet
        mock_data = mock_empty_samplesheet
    
    with patch('api.runs.services.get_run_samplesheet', return_value=mock_data):
        run_barcode = "190110_MACHINE123_0001_FLOWCELL123"
        response = client.get(f"/api/v1/runs/{run_barcode}/samplesheet")
        
        assert response.status_code == 200
        data = response.json()
        
        # Test expected number of samples
        assert len(data['Data']) == expected_samples
        
        # Test experiment name if expected
        if expected_experiment:
            assert data['Summary']['experiment_name'] == expected_experiment


def test_get_run_samplesheet_response_structure(client: TestClient, mock_illumina_samplesheet):
    """Test that the response has the correct IlluminaSampleSheetResponseModel structure"""
    
    with patch('api.runs.services.get_run_samplesheet', return_value=mock_illumina_samplesheet):
        run_barcode = "190110_MACHINE123_0001_FLOWCELL123"
        response = client.get(f"/api/v1/runs/{run_barcode}/samplesheet")
        
        assert response.status_code == 200
        data = response.json()
        
        # Verify all required fields are present
        required_fields = ['Summary', 'Header', 'Reads', 'Settings', 'DataCols', 'Data']
        for field in required_fields:
            assert field in data
        
        # Verify data types
        assert isinstance(data['Summary'], dict)
        assert isinstance(data['Header'], dict)
        assert isinstance(data['Reads'], dict)
        assert isinstance(data['Settings'], dict)
        assert isinstance(data['DataCols'], list)
        assert isinstance(data['Data'], list)
