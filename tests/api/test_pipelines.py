"""
Test /pipelines endpoint
"""

from unittest.mock import MagicMock, patch
from fastapi.testclient import TestClient
from sqlmodel import Session
import yaml


def test_get_pipeline_actions(client: TestClient):
    """Test retrieving available pipeline actions"""
    response = client.get("/api/v1/pipelines/actions")
    assert response.status_code == 200
    response_json = response.json()
    
    assert isinstance(response_json, list)
    assert len(response_json) == 2
    
    # Check structure of action options
    for action in response_json:
        assert "label" in action
        assert "value" in action
        assert "description" in action
    
    # Check specific actions
    action_values = [action["value"] for action in response_json]
    assert "create-project" in action_values
    assert "export-project-results" in action_values


def test_get_pipeline_platforms(client: TestClient):
    """Test retrieving available pipeline platforms"""
    response = client.get("/api/v1/pipelines/platforms")
    assert response.status_code == 200
    response_json = response.json()
    
    assert isinstance(response_json, list)
    assert len(response_json) == 2
    
    # Check structure of platform options
    for platform in response_json:
        assert "label" in platform
        assert "value" in platform
        assert "description" in platform
    
    # Check specific platforms
    platform_values = [platform["value"] for platform in response_json]
    assert "arvados" in platform_values
    assert "sevenbridges" in platform_values


@patch("api.pipelines.services.get_setting_value")
def test_get_pipeline_types(
    mock_get_setting: MagicMock,
    client: TestClient,
    session: Session,
    mock_s3_client
):
    """Test retrieving pipeline types based on action and platform"""
    
    # Mock S3 settings
    mock_get_setting.return_value = "s3://ngs360-resources/pipeline_configs/"
    
    # Setup mock S3 bucket data for the paginator
    files = [
        {"Key": "pipeline_configs/rna-seq_pipeline.yaml"}
    ]
    mock_s3_client.setup_bucket("ngs360-resources", "pipeline_configs/", files, [])
    
    # Mock get_object response with a sample pipeline config
    sample_config = {
        "project_type": "RNA-Seq",
        "project_admins": ["admin@example.com"],
        "platforms": {
            "Arvados": {
                "launchers": "rna-seq-launcher",
                "exports": [{"Raw Counts": "raw_counts"}]
            }
        }
    }
    
    # Store the file content in the mock S3 client's uploaded_files
    mock_s3_client.uploaded_files["ngs360-resources"] = {
        "pipeline_configs/rna-seq_pipeline.yaml": yaml.dump(sample_config).encode("utf-8")
    }
    
    # Test for create-project action
    response = client.get(
        "/api/v1/pipelines/types",
        params={"action": "create-project", "platform": "arvados"}
    )
    assert response.status_code == 200
    response_json = response.json()
    
    assert isinstance(response_json, list), f"Expected list, got {type(response_json)}"
    assert len(response_json) > 0, f"Expected non-empty list, got {response_json}"
    assert response_json[0]["project_type"] == "RNA-Seq"


@patch("api.pipelines.services.get_setting_value")
def test_validate_pipeline_config_success(
    mock_get_setting: MagicMock,
    client: TestClient,
    session: Session,
    mock_s3_client
):
    """Test validating a valid pipeline configuration"""
    # Mock S3 settings
    mock_get_setting.return_value = "s3://ngs360-resources/pipeline_configs/"
    
    # Mock get_object response with a valid pipeline config
    valid_config = {
        "project_type": "RNA-Seq",
        "project_admins": ["admin@example.com"],
        "platforms": {
            "Arvados": {
                "launchers": "rna-seq-launcher"
            }
        }
    }
    
    # Store the file content in the mock S3 client's uploaded_files
    mock_s3_client.uploaded_files["ngs360-resources"] = {
        "pipeline_configs/rna-seq_pipeline.yaml": yaml.dump(valid_config).encode("utf-8")
    }
    
    # Test validation
    response = client.post(
        "/api/v1/pipelines/validate",
        params={"s3_path": "rna-seq_pipeline.yaml"}
    )
    assert response.status_code == 200
    response_json = response.json()
    
    assert response_json["project_type"] == "RNA-Seq"
    assert "Arvados" in response_json["platforms"]


@patch("api.pipelines.services.get_setting_value")
def test_validate_pipeline_config_invalid_yaml(
    mock_get_setting: MagicMock,
    client: TestClient,
    session: Session,
    mock_s3_client
):
    """Test validating a pipeline configuration with invalid YAML"""
    # Mock S3 settings
    mock_get_setting.return_value = "s3://ngs360-resources/pipeline_configs/"
    
    # Store invalid YAML content in the mock S3 client's uploaded_files
    mock_s3_client.uploaded_files["ngs360-resources"] = {
        "pipeline_configs/invalid_pipeline.yaml": b"invalid: yaml: content: ["
    }
    
    # Test validation
    response = client.post(
        "/api/v1/pipelines/validate",
        params={"s3_path": "invalid_pipeline.yaml"}
    )
    assert response.status_code == 400
    response_json = response.json()
    assert "Invalid YAML format" in response_json["detail"]


@patch("api.pipelines.services.get_setting_value")
def test_validate_pipeline_config_missing_required_fields(
    mock_get_setting: MagicMock,
    client: TestClient,
    session: Session,
    mock_s3_client
):
    """Test validating a pipeline configuration with missing required fields"""
    # Mock S3 settings
    mock_get_setting.return_value = "s3://ngs360-resources/pipeline_configs/"
    
    # Mock get_object response with missing required fields
    invalid_config = {
        "project_type": "RNA-Seq"
        # Missing project_admins and platforms
    }
    
    # Store the file content in the mock S3 client's uploaded_files
    mock_s3_client.uploaded_files["ngs360-resources"] = {
        "pipeline_configs/incomplete_pipeline.yaml": yaml.dump(invalid_config).encode("utf-8")
    }
    
    # Test validation
    response = client.post(
        "/api/v1/pipelines/validate",
        params={"s3_path": "incomplete_pipeline.yaml"}
    )
    assert response.status_code == 422
    response_json = response.json()
    
    # Check that validation errors are returned
    assert "detail" in response_json


@patch("api.pipelines.services.get_setting_value")
def test_validate_pipeline_config_file_not_found(
    mock_get_setting: MagicMock,
    client: TestClient,
    session: Session,
    mock_s3_client
):
    """Test validating a non-existent pipeline configuration"""
    # Mock S3 settings
    mock_get_setting.return_value = "s3://ngs360-resources/pipeline_configs/"
    
    # Don't add the file to uploaded_files, so it will be not found
    
    # Test validation
    response = client.post(
        "/api/v1/pipelines/validate",
        params={"s3_path": "nonexistent_pipeline.yaml"}
    )
    assert response.status_code == 404
    response_json = response.json()
    assert "not found" in response_json["detail"].lower()
