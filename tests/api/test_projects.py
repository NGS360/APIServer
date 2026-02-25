"""
Test /projects endpoint

"""

from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient
from sqlmodel import Session
import yaml

from api.project.models import Project, ProjectAttribute
from api.project.services import generate_project_id


def test_get_projects_with_no_data(client: TestClient, session: Session):
    """Test that we can get projects when there is no data"""
    # Test No projects, this also ensure we are using the test db
    response = client.get("/api/v1/projects")
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


def test_get_projects_with_data(client: TestClient, session: Session):
    """Test that we can get projects"""
    # Add a project
    new_project = Project(name="AI Research")
    new_project.project_id = generate_project_id(session=session)

    # Initialize the attributes list if None
    new_project.attributes = [
        ProjectAttribute(key="description", value="Exploring AI techniques"),
        ProjectAttribute(key="Department", value="R&D"),
        ProjectAttribute(key="Priority", value="High"),
    ]

    session.add(new_project)
    session.commit()

    # Test with projects
    response = client.get("/api/v1/projects")
    assert response.status_code == 200
    response_json = response.json()

    # Check the data structure
    assert "data" in response_json
    assert len(response_json["data"]) == 1

    # Verify project details
    project = response_json["data"][0]
    assert project["name"] == "AI Research"

    assert project["data_folder_uri"] == f"s3://test-data-bucket/{new_project.project_id}/"
    assert project["results_folder_uri"] == f"s3://test-results-bucket/{new_project.project_id}/"

    # Check attributes (they're a list of objects with key/value pairs)
    attribute_dict = {attr["key"]: attr["value"] for attr in project["attributes"]}
    assert attribute_dict["description"] == "Exploring AI techniques"
    assert attribute_dict["Department"] == "R&D"
    assert attribute_dict["Priority"] == "High"


def test_create_project(client: TestClient):
    """Test that we can add a project"""
    data = {
        "name": "Test Project",
        "attributes": [
            {"key": "Department", "value": "R&D"},
            {"key": "Priority", "value": "High"},
        ],
    }
    # Test
    response = client.post("/api/v1/projects", json=data)
    # Check the response code
    assert response.status_code == 201
    json_response = response.json()
    # Validate project details
    assert "project_id" in json_response
    assert json_response["name"] == "Test Project"
    # Validate attributes
    assert "attributes" in json_response
    assert json_response["attributes"][0]["key"] == "Department"
    assert json_response["attributes"][0]["value"] == "R&D"
    assert json_response["attributes"][1]["key"] == "Priority"
    assert json_response["attributes"][1]["value"] == "High"


def test_create_project_fails_with_duplicate_attribute(client: TestClient):
    """Test that we can add a project"""
    data = {
        "name": "Test Project",
        "attributes": [
            {"key": "Department", "value": "R&D"},
            {"key": "Priority", "value": "High"},
            {"key": "Priority", "value": "Low"},
        ],
    }
    # Test
    response = client.post("/api/v1/projects", json=data)
    # Check the response code
    assert response.status_code == 400


def test_generate_project_id(session: Session):
    """Test that we can generate a project id"""
    # Generate a project id
    project_id = generate_project_id(session=session)
    # Check that the project id is not None
    assert project_id is not None
    # Check that the project id is a string
    assert isinstance(project_id, str)
    # Check that the project id is not empty
    assert len(project_id) > 0
    # Check that the project id ends with a 0001
    assert project_id.endswith("0001")
    # Add the project to the db
    project = Project(project_id=project_id, name="a project")
    session.add(project)
    session.flush()

    # Generate a 2nd project id
    project_id = generate_project_id(session=session)
    # Check that the project id ends with a 0002
    assert project_id.endswith("0002")


def test_get_project(client: TestClient, session: Session):
    """Test GET /api/projects/<project_id> works in different scenarios"""
    # Test when project not found and db is empty
    response = client.get("/api/v1/projects/Test_Project")
    assert response.status_code == 404

    # Add project to db
    new_project = Project(name="Test Project")
    new_project.project_id = generate_project_id(session=session)
    new_project.attributes = []
    session.add(new_project)
    session.commit()

    # Test when project not found and db is not empty
    response = client.get("/api/v1/projects/Test_Project")
    assert response.status_code == 404
    response = client.get("/api/v1/projects/test_project")
    assert response.status_code == 404

    # Test when project is found
    response = client.get(f"/api/v1/projects/{new_project.project_id}")
    assert response.status_code == 200
    response_json = response.json()
    assert response_json["name"] == "Test Project"
    assert response_json["project_id"] == new_project.project_id


def test_update_project_name(client: TestClient, session: Session):
    """Test that we can update a project's name"""
    # Create a project
    new_project = Project(name="Original Project Name")
    new_project.project_id = generate_project_id(session=session)
    new_project.attributes = []
    session.add(new_project)
    session.commit()

    # Update the project name
    update_data = {"name": "Updated Project Name"}
    response = client.put(f"/api/v1/projects/{new_project.project_id}", json=update_data)

    assert response.status_code == 200
    response_json = response.json()
    assert response_json["name"] == "Updated Project Name"
    assert response_json["project_id"] == new_project.project_id


def test_update_project_attributes(client: TestClient, session: Session):
    """Test that updating attributes replaces all existing attributes"""
    # Create a project with initial attributes
    new_project = Project(name="Test Project")
    new_project.project_id = generate_project_id(session=session)
    new_project.attributes = [
        ProjectAttribute(key="Department", value="R&D"),
        ProjectAttribute(key="Priority", value="Low"),
    ]
    session.add(new_project)
    session.commit()

    # Replace with new attributes (Priority will be removed, Department updated, Status added)
    update_data = {
        "attributes": [
            {"key": "Department", "value": "Engineering"},
            {"key": "Status", "value": "Active"},
        ]
    }
    response = client.put(f"/api/v1/projects/{new_project.project_id}", json=update_data)

    assert response.status_code == 200
    response_json = response.json()
    assert response_json["name"] == "Test Project"

    # Check attributes - should only have the two we sent (Priority was removed)
    assert len(response_json["attributes"]) == 2
    attribute_dict = {attr["key"]: attr["value"] for attr in response_json["attributes"]}
    assert attribute_dict["Department"] == "Engineering"
    assert attribute_dict["Status"] == "Active"
    assert "Priority" not in attribute_dict  # This was removed


def test_update_project_name_and_attributes(client: TestClient, session: Session):
    """Test that we can update both name and attributes together"""
    # Create a project
    new_project = Project(name="Original Name")
    new_project.project_id = generate_project_id(session=session)
    new_project.attributes = [
        ProjectAttribute(key="Department", value="R&D"),
    ]
    session.add(new_project)
    session.commit()

    # Update both name and attributes
    update_data = {
        "name": "Updated Name",
        "attributes": [
            {"key": "Department", "value": "Engineering"},
            {"key": "Priority", "value": "High"},
        ]
    }
    response = client.put(f"/api/v1/projects/{new_project.project_id}", json=update_data)

    assert response.status_code == 200
    response_json = response.json()
    assert response_json["name"] == "Updated Name"

    attribute_dict = {attr["key"]: attr["value"] for attr in response_json["attributes"]}
    assert attribute_dict["Department"] == "Engineering"
    assert attribute_dict["Priority"] == "High"


def test_update_project_not_found(client: TestClient):
    """Test that updating a non-existent project returns 404"""
    update_data = {"name": "New Name"}
    response = client.put("/api/v1/projects/nonexistent-project-id", json=update_data)

    assert response.status_code == 404
    assert "not found" in response.json()["detail"].lower()


def test_update_project_with_duplicate_attributes(client: TestClient, session: Session):
    """Test that updating with duplicate attribute keys fails"""
    # Create a project
    new_project = Project(name="Test Project")
    new_project.project_id = generate_project_id(session=session)
    new_project.attributes = []
    session.add(new_project)
    session.commit()

    # Try to update with duplicate keys
    update_data = {
        "attributes": [
            {"key": "Priority", "value": "High"},
            {"key": "Priority", "value": "Low"},
        ]
    }
    response = client.put(f"/api/v1/projects/{new_project.project_id}", json=update_data)

    assert response.status_code == 400
    assert "duplicate" in response.json()["detail"].lower()


def test_update_project_with_empty_data(client: TestClient, session: Session):
    """Test that updating with empty data doesn't change the project"""
    # Create a project
    new_project = Project(name="Original Name")
    new_project.project_id = generate_project_id(session=session)
    new_project.attributes = [
        ProjectAttribute(key="Department", value="R&D"),
    ]
    session.add(new_project)
    session.commit()

    # Update with empty data (all fields None)
    update_data = {}
    response = client.put(f"/api/v1/projects/{new_project.project_id}", json=update_data)

    assert response.status_code == 200
    response_json = response.json()
    assert response_json["name"] == "Original Name"
    assert len(response_json["attributes"]) == 1
    assert response_json["attributes"][0]["key"] == "Department"
    assert response_json["attributes"][0]["value"] == "R&D"


def test_update_project_replaces_all_attributes(client: TestClient, session: Session):
    """Test that updating attributes replaces all existing attributes"""
    # Create a project with three attributes
    new_project = Project(name="Test Project")
    new_project.project_id = generate_project_id(session=session)
    new_project.attributes = [
        ProjectAttribute(key="Department", value="R&D"),
        ProjectAttribute(key="Priority", value="High"),
        ProjectAttribute(key="Status", value="Active"),
    ]
    session.add(new_project)
    session.commit()

    # Update with only two attributes (effectively deleting "Status")
    update_data = {
        "attributes": [
            {"key": "Department", "value": "Engineering"},
            {"key": "Priority", "value": "Low"},
        ]
    }
    response = client.put(f"/api/v1/projects/{new_project.project_id}", json=update_data)

    assert response.status_code == 200
    response_json = response.json()

    # Should only have 2 attributes now
    assert len(response_json["attributes"]) == 2
    attribute_dict = {attr["key"]: attr["value"] for attr in response_json["attributes"]}
    assert attribute_dict["Department"] == "Engineering"
    assert attribute_dict["Priority"] == "Low"
    assert "Status" not in attribute_dict  # This attribute was deleted


def test_update_project_removes_all_attributes(client: TestClient, session: Session):
    """Test that updating with empty attributes list removes all attributes"""
    # Create a project with attributes
    new_project = Project(name="Test Project")
    new_project.project_id = generate_project_id(session=session)
    new_project.attributes = [
        ProjectAttribute(key="Department", value="R&D"),
        ProjectAttribute(key="Priority", value="High"),
    ]
    session.add(new_project)
    session.commit()

    # Update with empty attributes list
    update_data = {"attributes": []}
    response = client.put(f"/api/v1/projects/{new_project.project_id}", json=update_data)

    assert response.status_code == 200
    response_json = response.json()

    # Should have no attributes
    assert len(response_json["attributes"]) == 0


###############################################################################
# Pipeline Job Submission Tests
###############################################################################


@patch("api.jobs.services.boto3.client")
@patch("api.actions.services.get_setting_value")
def test_submit_create_project_job(
    mock_get_setting: MagicMock,
    mock_boto_client: MagicMock,
    client: TestClient,
    session: Session,
    test_project: Project,
    mock_s3_client
):
    """Test submitting a create-project job"""
    # Mock S3 settings
    mock_get_setting.return_value = "s3://ngs360-resources/pipeline_configs/"

    # Mock AWS Batch response
    mock_batch = MagicMock()
    mock_batch.submit_job.return_value = {
        "jobId": "aws-batch-job-123",
        "jobName": "create-rna-seq-project",
    }
    mock_boto_client.return_value = mock_batch

    # Setup mock pipeline config
    pipeline_config = {
        "project_type": "RNA-Seq",
        "project_admins": ["admin@example.com"],
        "platforms": {
            "Arvados": {
                "create_project_command": "arvados-create {{projectid}} --user {{username}}",
                "launchers": "rna-seq-launcher"
            }
        },
        "aws_batch": {
            "job_name": "create-{{project_type}}-{{projectid}}",
            "job_definition": "pipeline-job-def:1",
            "job_queue": "batch-queue",
            "command": "run_pipeline.sh {{action}}",
        }
    }

    files = [{"Key": "pipeline_configs/rna-seq_pipeline.yaml"}]
    mock_s3_client.setup_bucket("ngs360-resources", "pipeline_configs/", files, [])
    mock_s3_client.uploaded_files["ngs360-resources"] = {
        "pipeline_configs/rna-seq_pipeline.yaml": yaml.dump(pipeline_config).encode("utf-8")
    }

    # Submit pipeline job
    submit_data = {
        "action": "create-project",
        "platform": "Arvados",
        "project_type": "RNA-Seq"
    }

    response = client.post(
        f"/api/v1/projects/{test_project.project_id}/actions/submit",
        json=submit_data
    )

    assert response.status_code == 201
    response_json = response.json()

    # Verify response structure
    assert "id" in response_json
    assert response_json["aws_job_id"] == "aws-batch-job-123"
    assert response_json["status"] == "SUBMITTED"
    assert response_json["user"] == "testuser"

    # Verify AWS Batch was called with correct parameters
    mock_batch.submit_job.assert_called_once()
    call_args = mock_batch.submit_job.call_args[1]
    assert call_args["jobQueue"] == "batch-queue"
    assert call_args["jobDefinition"] == "pipeline-job-def:1"


@patch("api.jobs.services.boto3.client")
@patch("api.actions.services.get_setting_value")
def test_submit_export_results_job(
    mock_get_setting: MagicMock,
    mock_boto_client: MagicMock,
    client: TestClient,
    session: Session,
    test_project: Project,
    mock_s3_client
):
    """Test submitting an export-project-results pipeline job"""
    mock_get_setting.return_value = "s3://ngs360-resources/pipeline_configs/"

    # Mock AWS Batch response
    mock_batch = MagicMock()
    mock_batch.submit_job.return_value = {
        "jobId": "aws-batch-job-456",
        "jobName": "export-results",
    }
    mock_boto_client.return_value = mock_batch

    # Setup mock pipeline config with exports
    pipeline_config = {
        "project_type": "RNA-Seq",
        "project_admins": ["admin@example.com"],
        "platforms": {
            "Arvados": {
                "create_project_command": "arvados-create",
                "export_command": (
                    "arvados-export {{projectid}} --reference {{reference}} "
                    "--auto-release {{auto_release}}"
                ),
                "launchers": "rna-seq-launcher",
                "exports": [
                    {"Raw Counts": "raw_counts"},
                    {"Normalized Counts": "normalized_counts"}
                ]
            }
        },
        "aws_batch": {
            "job_name": "export-{{projectid}}",
            "job_definition": "export-job-def:1",
            "job_queue": "export-queue",
            "command": "run_export.sh",
            "environment": [
                {"name": "PROJECT_ID", "value": "{{projectid}}"},
                {"name": "REFERENCE", "value": "{{reference}}"}
            ]
        }
    }

    files = [{"Key": "pipeline_configs/rna-seq_pipeline.yaml"}]
    mock_s3_client.setup_bucket("ngs360-resources", "pipeline_configs/", files, [])
    mock_s3_client.uploaded_files["ngs360-resources"] = {
        "pipeline_configs/rna-seq_pipeline.yaml": yaml.dump(pipeline_config).encode("utf-8")
    }

    # Submit export pipeline job
    submit_data = {
        "action": "export-project-results",
        "platform": "Arvados",
        "project_type": "RNA-Seq",
        "reference": "Raw Counts",
        "auto_release": True
    }

    response = client.post(
        f"/api/v1/projects/{test_project.project_id}/actions/submit",
        json=submit_data
    )

    assert response.status_code == 201
    response_json = response.json()
    assert response_json["aws_job_id"] == "aws-batch-job-456"
    assert response_json["status"] == "SUBMITTED"

    # Verify AWS Batch was called
    mock_batch.submit_job.assert_called_once()
    call_args = mock_batch.submit_job.call_args[1]

    # Check environment variables were interpolated
    env_vars = call_args["containerOverrides"]["environment"]
    project_id_env = next(
        (e for e in env_vars if e["name"] == "PROJECT_ID"), None
    )
    assert project_id_env is not None
    assert project_id_env["value"] == test_project.project_id

    reference_env = next((e for e in env_vars if e["name"] == "REFERENCE"), None)
    assert reference_env is not None
    assert reference_env["value"] == "raw_counts"  # The value, not the label


@patch("api.jobs.services.boto3.client")
@patch("api.actions.services.get_setting_value")
def test_submit_pipeline_job_export_without_reference(
    mock_get_setting: MagicMock,
    mock_boto_client: MagicMock,
    client: TestClient,
    session: Session,
    test_project: Project,
    mock_s3_client
):
    """Test that export action without reference returns 400"""
    mock_get_setting.return_value = "s3://ngs360-resources/pipeline_configs/"

    pipeline_config = {
        "project_type": "RNA-Seq",
        "project_admins": ["admin@example.com"],
        "platforms": {
            "Arvados": {
                "export_command": "arvados-export",
                "exports": [{"Raw Counts": "raw_counts"}]
            }
        },
        "aws_batch": {
            "job_name": "export-job",
            "job_definition": "export-def:1",
            "job_queue": "queue",
            "command": "run.sh"
        }
    }

    files = [{"Key": "pipeline_configs/rna-seq_pipeline.yaml"}]
    mock_s3_client.setup_bucket("ngs360-resources", "pipeline_configs/", files, [])
    mock_s3_client.uploaded_files["ngs360-resources"] = {
        "pipeline_configs/rna-seq_pipeline.yaml": yaml.dump(pipeline_config).encode("utf-8")
    }

    # Submit without reference
    submit_data = {
        "action": "export-project-results",
        "platform": "Arvados",
        "project_type": "RNA-Seq"
        # Missing reference
    }

    response = client.post(
        f"/api/v1/projects/{test_project.project_id}/actions/submit",
        json=submit_data
    )

    assert response.status_code == 400
    assert "Reference is required" in response.json()["detail"]


@patch("api.jobs.services.boto3.client")
@patch("api.actions.services.get_setting_value")
def test_submit_create_project_with_auto_release_ignored(
    mock_get_setting: MagicMock,
    mock_boto_client: MagicMock,
    client: TestClient,
    session: Session,
    test_project: Project,
    mock_s3_client
):
    """Test that create-project action ignores auto_release parameter and succeeds"""
    mock_get_setting.return_value = "s3://ngs360-resources/pipeline_configs/"

    # Mock AWS Batch response
    mock_batch = MagicMock()
    mock_batch.submit_job.return_value = {
        "jobId": "aws-batch-job-789",
        "jobName": "create-job",
    }
    mock_boto_client.return_value = mock_batch

    pipeline_config = {
        "project_type": "RNA-Seq",
        "project_admins": ["admin@example.com"],
        "platforms": {
            "Arvados": {
                "create_project_command": "arvados-create",
                "launchers": "launcher"
            }
        },
        "aws_batch": {
            "job_name": "create-job",
            "job_definition": "create-def:1",
            "job_queue": "queue",
            "command": "run.sh"
        }
    }

    files = [{"Key": "pipeline_configs/rna-seq_pipeline.yaml"}]
    mock_s3_client.setup_bucket("ngs360-resources", "pipeline_configs/", files, [])
    mock_s3_client.uploaded_files["ngs360-resources"] = {
        "pipeline_configs/rna-seq_pipeline.yaml": yaml.dump(pipeline_config).encode("utf-8")
    }

    # Submit with auto_release (should be ignored for create-project)
    submit_data = {
        "action": "create-project",
        "platform": "Arvados",
        "project_type": "RNA-Seq",
        "auto_release": True  # Should be ignored for create action
    }

    response = client.post(
        f"/api/v1/projects/{test_project.project_id}/actions/submit",
        json=submit_data
    )

    # Should succeed and ignore auto_release
    assert response.status_code == 201
    response_json = response.json()
    assert response_json["aws_job_id"] == "aws-batch-job-789"
    assert response_json["status"] == "SUBMITTED"


@patch("api.actions.services.get_setting_value")
def test_submit_pipeline_job_nonexistent_project(
    mock_get_setting: MagicMock,
    client: TestClient,
    session: Session,
    mock_s3_client
):
    """Test submitting a pipeline job for a non-existent project returns 404"""
    mock_get_setting.return_value = "s3://ngs360-resources/pipeline_configs/"

    submit_data = {
        "action": "create-project",
        "platform": "Arvados",
        "project_type": "RNA-Seq"
    }

    response = client.post(
        "/api/v1/projects/P-99999999-9999/actions/submit",
        json=submit_data
    )

    assert response.status_code == 404


@patch("api.jobs.services.boto3.client")
@patch("api.actions.services.get_setting_value")
def test_submit_pipeline_job_nonexistent_pipeline_type(
    mock_get_setting: MagicMock,
    mock_boto_client: MagicMock,
    client: TestClient,
    session: Session,
    test_project: Project,
    mock_s3_client
):
    """Test submitting a pipeline job with non-existent pipeline type returns 404"""
    mock_get_setting.return_value = "s3://ngs360-resources/pipeline_configs/"

    # Setup with a different pipeline type
    pipeline_config = {
        "project_type": "RNA-Seq",
        "project_admins": ["admin@example.com"],
        "platforms": {
            "Arvados": {
                "create_project_command": "create"
            }
        },
        "aws_batch": {
            "job_name": "job",
            "job_definition": "def:1",
            "job_queue": "queue",
            "command": "run.sh"
        }
    }

    files = [{"Key": "pipeline_configs/rna-seq_pipeline.yaml"}]
    mock_s3_client.setup_bucket("ngs360-resources", "pipeline_configs/", files, [])
    mock_s3_client.uploaded_files["ngs360-resources"] = {
        "pipeline_configs/rna-seq_pipeline.yaml": yaml.dump(pipeline_config).encode("utf-8")
    }

    # Try to submit with non-existent pipeline type
    submit_data = {
        "action": "create-project",
        "platform": "Arvados",
        "project_type": "NonExistentPipeline"
    }

    response = client.post(
        f"/api/v1/projects/{test_project.project_id}/actions/submit",
        json=submit_data
    )

    assert response.status_code == 404
    assert "Action configuration for project type" in response.json()["detail"]


@patch("api.jobs.services.boto3.client")
@patch("api.actions.services.get_setting_value")
def test_submit_pipeline_job_platform_not_configured(
    mock_get_setting: MagicMock,
    mock_boto_client: MagicMock,
    client: TestClient,
    session: Session,
    test_project: Project,
    mock_s3_client
):
    """Test submitting a pipeline job for a platform not configured in the pipeline"""
    mock_get_setting.return_value = "s3://ngs360-resources/pipeline_configs/"

    # Setup pipeline with only Arvados platform
    pipeline_config = {
        "project_type": "RNA-Seq",
        "project_admins": ["admin@example.com"],
        "platforms": {
            "Arvados": {
                "create_project_command": "create"
            }
        },
        "aws_batch": {
            "job_name": "job",
            "job_definition": "def:1",
            "job_queue": "queue",
            "command": "run.sh"
        }
    }

    files = [{"Key": "pipeline_configs/rna-seq_pipeline.yaml"}]
    mock_s3_client.setup_bucket("ngs360-resources", "pipeline_configs/", files, [])
    mock_s3_client.uploaded_files["ngs360-resources"] = {
        "pipeline_configs/rna-seq_pipeline.yaml": yaml.dump(pipeline_config).encode("utf-8")
    }

    # Try to submit for SevenBridges platform (not configured)
    submit_data = {
        "action": "create-project",
        "platform": "SevenBridges",
        "project_type": "RNA-Seq"
    }

    response = client.post(
        f"/api/v1/projects/{test_project.project_id}/actions/submit",
        json=submit_data
    )

    assert response.status_code == 400
    assert "Platform" in response.json()["detail"]
    assert "not configured" in response.json()["detail"]


@patch("api.jobs.services.boto3.client")
@patch("api.actions.services.get_setting_value")
def test_submit_pipeline_job_missing_aws_batch_config(
    mock_get_setting: MagicMock,
    mock_boto_client: MagicMock,
    client: TestClient,
    session: Session,
    test_project: Project,
    mock_s3_client
):
    """Test submitting a pipeline job without AWS Batch configuration returns 400"""
    mock_get_setting.return_value = "s3://ngs360-resources/pipeline_configs/"

    # Setup pipeline without aws_batch config
    pipeline_config = {
        "project_type": "RNA-Seq",
        "project_admins": ["admin@example.com"],
        "platforms": {
            "Arvados": {
                "create_project_command": "create"
            }
        }
        # Missing aws_batch configuration
    }

    files = [{"Key": "pipeline_configs/rna-seq_pipeline.yaml"}]
    mock_s3_client.setup_bucket("ngs360-resources", "pipeline_configs/", files, [])
    mock_s3_client.uploaded_files["ngs360-resources"] = {
        "pipeline_configs/rna-seq_pipeline.yaml": yaml.dump(pipeline_config).encode("utf-8")
    }

    submit_data = {
        "action": "create-project",
        "platform": "Arvados",
        "project_type": "RNA-Seq"
    }

    response = client.post(
        f"/api/v1/projects/{test_project.project_id}/actions/submit",
        json=submit_data
    )

    assert response.status_code == 400
    assert "AWS Batch configuration not found" in response.json()["detail"]


@patch("api.jobs.services.boto3.client")
@patch("api.actions.services.get_setting_value")
def test_submit_pipeline_job_invalid_reference(
    mock_get_setting: MagicMock,
    mock_boto_client: MagicMock,
    client: TestClient,
    session: Session,
    test_project: Project,
    mock_s3_client
):
    """Test submitting export job with invalid reference returns 400"""
    mock_get_setting.return_value = "s3://ngs360-resources/pipeline_configs/"

    pipeline_config = {
        "project_type": "RNA-Seq",
        "project_admins": ["admin@example.com"],
        "platforms": {
            "Arvados": {
                "export_command": "export",
                "exports": [
                    {"Raw Counts": "raw_counts"},
                    {"Normalized Counts": "normalized_counts"}
                ]
            }
        },
        "aws_batch": {
            "job_name": "export-job",
            "job_definition": "export-def:1",
            "job_queue": "queue",
            "command": "run.sh"
        }
    }

    files = [{"Key": "pipeline_configs/rna-seq_pipeline.yaml"}]
    mock_s3_client.setup_bucket("ngs360-resources", "pipeline_configs/", files, [])
    mock_s3_client.uploaded_files["ngs360-resources"] = {
        "pipeline_configs/rna-seq_pipeline.yaml": yaml.dump(pipeline_config).encode("utf-8")
    }

    # Submit with invalid reference
    submit_data = {
        "action": "export-project-results",
        "platform": "Arvados",
        "project_type": "RNA-Seq",
        "reference": "InvalidReference"
    }

    response = client.post(
        f"/api/v1/projects/{test_project.project_id}/actions/submit",
        json=submit_data
    )

    assert response.status_code == 400
    assert "Reference" in response.json()["detail"]
    assert "not found in exports" in response.json()["detail"]


@patch("api.jobs.services.boto3.client")
@patch("api.actions.services.get_setting_value")
def test_submit_pipeline_job_template_interpolation(
    mock_get_setting: MagicMock,
    mock_boto_client: MagicMock,
    client: TestClient,
    session: Session,
    test_project: Project,
    mock_s3_client
):
    """Test that template variables are correctly interpolated"""
    mock_get_setting.return_value = "s3://ngs360-resources/pipeline_configs/"

    # Track the actual command sent to AWS Batch
    mock_batch = MagicMock()
    mock_batch.submit_job.return_value = {
        "jobId": "aws-batch-job-789",
        "jobName": "interpolated-job",
    }
    mock_boto_client.return_value = mock_batch

    pipeline_config = {
        "project_type": "RNA-Seq",
        "project_admins": ["admin@example.com"],
        "platforms": {
            "Arvados": {
                "create_project_command": (
                    "create-project --id {{projectid}} --user {{username}} "
                    "--type {{project_type}}"
                )
            }
        },
        "aws_batch": {
            "job_name": "{{action}}-{{project_type}}-{{projectid}}",
            "job_definition": "def:1",
            "job_queue": "queue",
            "command": "run.sh {{action}} {{projectid}}",
            "environment": [
                {"name": "USER", "value": "{{username}}"},
                {"name": "PROJECT_TYPE", "value": "{{project_type}}"}
            ]
        }
    }

    files = [{"Key": "pipeline_configs/rna-seq_pipeline.yaml"}]
    mock_s3_client.setup_bucket("ngs360-resources", "pipeline_configs/", files, [])
    mock_s3_client.uploaded_files["ngs360-resources"] = {
        "pipeline_configs/rna-seq_pipeline.yaml": yaml.dump(pipeline_config).encode("utf-8")
    }

    submit_data = {
        "action": "create-project",
        "platform": "Arvados",
        "project_type": "RNA-Seq"
    }

    response = client.post(
        f"/api/v1/projects/{test_project.project_id}/actions/submit",
        json=submit_data
    )

    assert response.status_code == 201

    # Verify AWS Batch was called with interpolated values
    call_args = mock_batch.submit_job.call_args[1]

    # Check job name was interpolated
    assert call_args["jobName"] == f"create-project-RNA-Seq-{test_project.project_id}"

    # Check command was interpolated
    command = call_args["containerOverrides"]["command"]
    assert "create-project" in " ".join(command)
    assert test_project.project_id in " ".join(command)

    # Check environment variables were interpolated
    env_vars = call_args["containerOverrides"]["environment"]
    user_env = next((e for e in env_vars if e["name"] == "USER"), None)
    assert user_env is not None
    assert user_env["value"] == "testuser"

    project_type_env = next((e for e in env_vars if e["name"] == "PROJECT_TYPE"), None)
    assert project_type_env is not None
    assert project_type_env["value"] == "RNA-Seq"


@patch("api.jobs.services.boto3.client")
@patch("api.project.services.get_setting")
def test_ingest_vendor_data(
    mock_get_setting: MagicMock,
    mock_boto_client: MagicMock,
    client: TestClient,
    test_project: Project,
):
    """Test the ingest vendor data endpoint"""
    # Set up test parameters
    # Set up supporting mocks
    mock_get_setting.return_value = "config/vendor_ingestion.yaml"

    mock_batch = MagicMock()
    mock_batch.submit_job.return_value = {
        "jobId": "aws-batch-job-123",
        "jobName": "aws-batch-job-123",
    }
    mock_boto_client.return_value = mock_batch

    # Test
    response = client.post(
        f"/api/v1/projects/{test_project.project_id}/ingest?"
        "files_uri=s3://vendor-data-bucket/incoming/project123&"
        "manifest_uri=s3://vendor-data-bucket/project123/manifest.csv"
    )
    # Check results
    assert response.status_code == 201
    response_json = response.json()
    assert response_json["aws_job_id"] == "aws-batch-job-123"
