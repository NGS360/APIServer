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
    assert "Arvados" in platform_values
    assert "SevenBridges" in platform_values


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
        params={"action": "create-project", "platform": "Arvados"}
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


@patch("api.pipelines.services.get_setting_value")
def test_validate_pipeline_config_full_s3_uri(
    mock_get_setting: MagicMock,
    client: TestClient,
    session: Session,
    mock_s3_client
):
    """Test validating a pipeline configuration with a full S3 URI"""
    # Mock S3 settings (not used in this test as we provide full URI)
    mock_get_setting.return_value = "s3://ngs360-resources/pipeline_configs/"

    # Mock valid config in a different bucket
    valid_config = {
        "project_type": "WGS",
        "project_admins": ["admin@example.com"],
        "platforms": {
            "SevenBridges": {
                "launchers": "wgs-launcher"
            }
        }
    }

    # Store in a different bucket
    mock_s3_client.uploaded_files["custom-bucket"] = {
        "custom/path/wgs_pipeline.yaml": yaml.dump(valid_config).encode("utf-8")
    }

    # Test validation with full S3 URI
    response = client.post(
        "/api/v1/pipelines/validate",
        params={"s3_path": "s3://custom-bucket/custom/path/wgs_pipeline.yaml"}
    )
    assert response.status_code == 200
    response_json = response.json()
    assert response_json["project_type"] == "WGS"


@patch("api.pipelines.services.get_setting_value")
def test_validate_pipeline_config_with_aws_batch(
    mock_get_setting: MagicMock,
    client: TestClient,
    session: Session,
    mock_s3_client
):
    """Test validating a pipeline configuration with AWS Batch settings"""
    mock_get_setting.return_value = "s3://ngs360-resources/pipeline_configs/"

    valid_config = {
        "project_type": "ChIP-Seq",
        "project_admins": ["admin@example.com"],
        "platforms": {
            "Arvados": {
                "create_project_command": "launch-project",
                "export_command": "export-results"
            }
        },
        "aws_batch": {
            "job_name": "chipseq-{{projectid}}",
            "job_definition": "chipseq-job-def:1",
            "job_queue": "batch-queue",
            "command": "run_pipeline.sh",
            "environment": [
                {"name": "PROJECT_ID", "value": "{{projectid}}"},
                {"name": "USER", "value": "{{username}}"}
            ]
        }
    }

    mock_s3_client.uploaded_files["ngs360-resources"] = {
        "pipeline_configs/chipseq_pipeline.yaml": yaml.dump(valid_config).encode("utf-8")
    }

    response = client.post(
        "/api/v1/pipelines/validate",
        params={"s3_path": "chipseq_pipeline.yaml"}
    )
    assert response.status_code == 200
    response_json = response.json()
    assert response_json["project_type"] == "ChIP-Seq"
    assert "aws_batch" in response_json
    assert response_json["aws_batch"]["job_name"] == "chipseq-{{projectid}}"
    assert len(response_json["aws_batch"]["environment"]) == 2


@patch("api.pipelines.services.get_setting_value")
def test_get_pipeline_types_export_action(
    mock_get_setting: MagicMock,
    client: TestClient,
    session: Session,
    mock_s3_client
):
    """Test retrieving pipeline types for export action"""
    mock_get_setting.return_value = "s3://ngs360-resources/pipeline_configs/"

    # Setup mock S3 bucket data
    files = [
        {"Key": "pipeline_configs/rna-seq_pipeline.yaml"}
    ]
    mock_s3_client.setup_bucket("ngs360-resources", "pipeline_configs/", files, [])

    # Mock pipeline config with exports
    sample_config = {
        "project_type": "RNA-Seq",
        "project_admins": ["admin@example.com"],
        "platforms": {
            "Arvados": {
                "launchers": "rna-seq-launcher",
                "exports": [
                    {"Raw Counts": "raw_counts"},
                    {"Normalized Counts": "normalized_counts"}
                ]
            }
        }
    }

    mock_s3_client.uploaded_files["ngs360-resources"] = {
        "pipeline_configs/rna-seq_pipeline.yaml": yaml.dump(sample_config).encode("utf-8")
    }

    # Test for export action
    response = client.get(
        "/api/v1/pipelines/types",
        params={"action": "export-project-results", "platform": "Arvados"}
    )
    assert response.status_code == 200
    response_json = response.json()

    assert isinstance(response_json, list)
    assert len(response_json) == 2

    # Check that exports are returned
    labels = [item["label"] for item in response_json]
    assert "Raw Counts" in labels
    assert "Normalized Counts" in labels

    # Verify project_type is included
    assert all(item["project_type"] == "RNA-Seq" for item in response_json)


@patch("api.pipelines.services.get_setting_value")
def test_get_pipeline_types_invalid_platform(
    mock_get_setting: MagicMock,
    client: TestClient,
    session: Session,
    mock_s3_client
):
    """Test getting pipeline types with invalid platform returns 422"""
    mock_get_setting.return_value = "s3://ngs360-resources/pipeline_configs/"

    response = client.get(
        "/api/v1/pipelines/types",
        params={"action": "create-project", "platform": "InvalidPlatform"}
    )
    # FastAPI validation returns 422 for invalid Literal values
    assert response.status_code == 422
    response_json = response.json()
    assert "detail" in response_json


@patch("api.pipelines.services.get_setting_value")
def test_get_pipeline_types_no_configs(
    mock_get_setting: MagicMock,
    client: TestClient,
    session: Session,
    mock_s3_client
):
    """Test getting pipeline types when no configs exist"""
    mock_get_setting.return_value = "s3://ngs360-resources/pipeline_configs/"

    # Setup empty bucket
    mock_s3_client.setup_bucket("ngs360-resources", "pipeline_configs/", [], [])

    response = client.get(
        "/api/v1/pipelines/types",
        params={"action": "create-project", "platform": "Arvados"}
    )
    assert response.status_code == 200
    response_json = response.json()
    assert isinstance(response_json, list)
    assert len(response_json) == 0
