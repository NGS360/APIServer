"""
Test /projects endpoint

"""

import copy
from datetime import datetime, timedelta, timezone
import json
from unittest.mock import patch, MagicMock

import botocore.exceptions
import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select
import yaml

from api.platforms.models import Platform
from api.project.models import Project, ProjectAttribute, ProjectWorkflowVersion
from api.project.services import generate_project_id
from api.workflow.models import (
    Workflow,
    WorkflowDeployment,
    WorkflowVersion,
    WorkflowVersionAlias,
)


def _create_project(session: Session):
    new_project = Project(name="Test Project", created_by="testuser")
    new_project.project_id = generate_project_id(session=session)
    new_project.attributes = []
    session.add(new_project)
    session.commit()


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
    new_project = Project(name="AI Research", created_by="testuser")
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


def test_get_projects_attributes(client: TestClient, session: Session):
    """Test that we get a full list of all attributes across all projects"""
    # Add two projects with different attributes
    project1 = Project(name="Project One", created_by='testuser')
    project1.project_id = generate_project_id(session=session)
    project1.attributes = [
        ProjectAttribute(key="Department", value="R&D"),
        ProjectAttribute(key="Priority", value="High"),
    ]
    session.add(project1)

    project2 = Project(name="Project Two", created_by='testuser')
    project2.project_id = generate_project_id(session=session)
    project2.attributes = [
        ProjectAttribute(key="Department", value="Engineering"),
        ProjectAttribute(key="Status", value="Active"),
    ]
    session.add(project2)
    session.commit()

    # Get project attributes
    response = client.get("/api/v1/projects/attributes")
    assert response.status_code == 200
    response_json = response.json()

    expected_attributes = ["Department", "Priority", "Status"]
    assert response_json == expected_attributes


def test_get_project_with_sequencing_runs(client: TestClient, session: Session):
    """Test that GET /api/projects/<project_id> includes associated sequencing runs"""
    from datetime import date
    from api.project.models import Project
    from api.project.services import generate_project_id
    from api.samples.models import Sample
    from api.runs.models import SequencingRun, SampleSequencingRun, RunStatus

    # Create a project
    project = Project(name="Test Project with Runs", created_by="testuser")
    project.project_id = generate_project_id(session=session)
    session.add(project)
    session.flush()

    # Create samples for the project
    sample1 = Sample(sample_id="SAMPLE-001", project_id=project.project_id)
    sample2 = Sample(sample_id="SAMPLE-002", project_id=project.project_id)
    session.add(sample1)
    session.add(sample2)
    session.flush()

    # Create sequencing runs
    run1 = SequencingRun(
        run_id="240115_M12345_100_FC001",
        run_date=date(2024, 1, 15),
        machine_id="M12345",
        run_number="100",
        flowcell_id="FC001",
        experiment_name="Experiment-001",
        run_folder_uri="s3://runs/run1/",
        status=RunStatus.READY
    )
    run2 = SequencingRun(
        run_id="240220_M67890_200_FC002",
        run_date=date(2024, 2, 20),
        machine_id="M67890",
        run_number="200",
        flowcell_id="FC002",
        experiment_name="Experiment-002",
        run_folder_uri="s3://runs/run2/",
        status=RunStatus.UPLOADING
    )
    session.add(run1)
    session.add(run2)
    session.flush()

    # Associate samples with sequencing runs
    # sample1 is on both runs, sample2 is only on run2
    assoc1 = SampleSequencingRun(
        sample_id=sample1.id,
        sequencing_run_id=run1.id,
        created_by="testuser"
    )
    assoc2 = SampleSequencingRun(
        sample_id=sample1.id,
        sequencing_run_id=run2.id,
        created_by="testuser"
    )
    assoc3 = SampleSequencingRun(
        sample_id=sample2.id,
        sequencing_run_id=run2.id,
        created_by="testuser"
    )
    session.add(assoc1)
    session.add(assoc2)
    session.add(assoc3)
    session.commit()

    # Get the project
    response = client.get(f"/api/v1/projects/{project.project_id}")
    assert response.status_code == 200
    response_json = response.json()

    # Verify basic project details
    assert response_json["name"] == "Test Project with Runs"
    assert response_json["project_id"] == project.project_id

    # Verify sequencing_runs field exists
    assert "sequencing_runs" in response_json
    assert response_json["sequencing_runs"] is not None

    # Should have 2 distinct sequencing runs
    sequencing_runs = response_json["sequencing_runs"]
    assert len(sequencing_runs) == 2

    # Sort by run_number for predictable ordering
    sequencing_runs.sort(key=lambda r: int(r["run_number"]))

    # Verify first run details
    assert sequencing_runs[0]["machine_id"] == "M12345"
    assert sequencing_runs[0]["run_number"] == "100"
    assert sequencing_runs[0]["flowcell_id"] == "FC001"
    assert sequencing_runs[0]["experiment_name"] == "Experiment-001"
    assert sequencing_runs[0]["status"] == "Ready"
    assert sequencing_runs[0]["run_id"] == "240115_M12345_100_FC001"

    # Verify second run details
    assert sequencing_runs[1]["machine_id"] == "M67890"
    assert sequencing_runs[1]["run_number"] == "200"
    assert sequencing_runs[1]["flowcell_id"] == "FC002"
    assert sequencing_runs[1]["experiment_name"] == "Experiment-002"
    assert sequencing_runs[1]["status"] == "Uploading"
    assert sequencing_runs[1]["run_id"] == "240220_M67890_200_FC002"


def test_get_project_without_sequencing_runs(client: TestClient, session: Session):
    """
    Test that GET /api/projects/<project_id> returns empty list
    when no sequencing runs associated with project
    """
    from api.project.models import Project
    from api.project.services import generate_project_id

    # Create a project with no samples or runs
    project = Project(name="Project Without Runs", created_by="testuser")
    project.project_id = generate_project_id(session=session)
    session.add(project)
    session.commit()

    # Get the project
    response = client.get(f"/api/v1/projects/{project.project_id}")
    assert response.status_code == 200
    response_json = response.json()

    # Verify project details
    assert response_json["name"] == "Project Without Runs"
    assert response_json["project_id"] == project.project_id

    # Verify sequencing_runs field exists and is empty
    assert "sequencing_runs" in response_json
    assert response_json["sequencing_runs"] is not None
    assert len(response_json["sequencing_runs"]) == 0


def test_get_project_with_samples_but_no_runs(client: TestClient, session: Session):
    """Test project with samples but no associated sequencing runs"""
    from api.project.models import Project
    from api.project.services import generate_project_id
    from api.samples.models import Sample

    # Create a project with samples but no runs
    project = Project(name="Project With Samples No Runs", created_by="testuser")
    project.project_id = generate_project_id(session=session)
    session.add(project)
    session.flush()

    # Create samples but don't associate them with any runs
    sample1 = Sample(sample_id="SAMPLE-A", project_id=project.project_id)
    sample2 = Sample(sample_id="SAMPLE-B", project_id=project.project_id)
    session.add(sample1)
    session.add(sample2)
    session.commit()

    # Get the project
    response = client.get(f"/api/v1/projects/{project.project_id}")
    assert response.status_code == 200
    response_json = response.json()

    # Verify project details
    assert response_json["name"] == "Project With Samples No Runs"

    # Should have empty sequencing runs list
    assert "sequencing_runs" in response_json
    assert response_json["sequencing_runs"] == []


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


def test_create_project_fails_with_case_insensitive_duplicate_attribute(
    client: TestClient,
):
    """Test that creating a project with attribute keys differing only in case returns 400."""
    data = {
        "name": "Test Project",
        "attributes": [
            {"key": "Priority", "value": "High"},
            {"key": "priority", "value": "Low"},
        ],
    }
    response = client.post("/api/v1/projects", json=data)
    assert response.status_code == 400
    assert "duplicate" in response.json()["detail"].lower()


def test_create_project_strips_whitespace_from_attribute(client: TestClient):
    """
    Test that creating a project with attribute keys containing leading/trailing whitespace
    strips the whitespace before saving.
    """
    data = {
        "name": "Test Project",
        "attributes": [
            {"key": " Priority ", "value": "High"},
            {"key": "Genome", "value": " hg38 "},
        ],
    }
    response = client.post("/api/v1/projects", json=data)
    assert response.status_code == 201
    response_json = response.json()
    # Validate that whitespace is stripped
    for attr in response_json["attributes"]:
        assert attr["key"] == attr["key"].strip()
        assert attr["value"] == attr["value"].strip()


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
    project = Project(project_id=project_id, name="a project", created_by="testuser")
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
    new_project = Project(name="Test Project", created_by="testuser")
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
    new_project = Project(name="Original Project Name", created_by="testuser")
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
    new_project = Project(name="Test Project", created_by="testuser")
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
    new_project = Project(name="Original Name", created_by="testuser")
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
    new_project = Project(name="Test Project", created_by="testuser")
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


def test_update_project_with_case_insensitive_duplicate_attributes(
    client: TestClient, session: Session
):
    """Test that PUT update with attribute keys differing only in case returns 400."""
    new_project = Project(name="Test Project", created_by="testuser")
    new_project.project_id = generate_project_id(session=session)
    new_project.attributes = []
    session.add(new_project)
    session.commit()

    update_data = {
        "attributes": [
            {"key": "Priority", "value": "High"},
            {"key": "priority", "value": "Low"},
        ]
    }
    response = client.put(
        f"/api/v1/projects/{new_project.project_id}", json=update_data
    )
    assert response.status_code == 400
    assert "duplicate" in response.json()["detail"].lower()


def test_update_project_with_empty_data(client: TestClient, session: Session):
    """Test that updating with empty data doesn't change the project"""
    # Create a project
    new_project = Project(name="Original Name", created_by="testuser")
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
    new_project = Project(name="Test Project", created_by="testuser")
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
    new_project = Project(name="Test Project", created_by="testuser")
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
# PATCH Project Tests (merge/upsert semantics)
###############################################################################


def test_patch_project_merge_preserves_existing(
    client: TestClient, session: Session
):
    """Test that PATCH with a new attribute preserves all existing attributes"""
    new_project = Project(name="Test Project", created_by="testuser")
    new_project.project_id = generate_project_id(session=session)
    new_project.attributes = [
        ProjectAttribute(key="project_type", value="RNA-Seq"),
        ProjectAttribute(key="pi", value="Dr. Smith"),
    ]
    session.add(new_project)
    session.commit()

    # Add a single new attribute (simulates NGS-BMS worker)
    update_data = {
        "attributes": [
            {"key": "xpress_project_id", "value": "-1"},
        ]
    }
    response = client.patch(
        f"/api/v1/projects/{new_project.project_id}",
        json=update_data,
    )

    assert response.status_code == 200
    response_json = response.json()

    # All three attributes should be present
    assert len(response_json["attributes"]) == 3
    attr_dict = {
        a["key"]: a["value"] for a in response_json["attributes"]
    }
    assert attr_dict["project_type"] == "RNA-Seq"
    assert attr_dict["pi"] == "Dr. Smith"
    assert attr_dict["xpress_project_id"] == "-1"


def test_patch_project_upsert_existing_key(
    client: TestClient, session: Session
):
    """Test that PATCH with an existing key updates only that value"""
    new_project = Project(name="Test Project", created_by="testuser")
    new_project.project_id = generate_project_id(session=session)
    new_project.attributes = [
        ProjectAttribute(key="project_type", value="RNA-Seq"),
        ProjectAttribute(key="xpress_project_id", value="-1"),
        ProjectAttribute(key="pi", value="Dr. Smith"),
    ]
    session.add(new_project)
    session.commit()

    update_data = {
        "attributes": [
            {"key": "xpress_project_id", "value": "12345"},
        ]
    }
    response = client.patch(
        f"/api/v1/projects/{new_project.project_id}",
        json=update_data,
    )

    assert response.status_code == 200
    response_json = response.json()

    assert len(response_json["attributes"]) == 3
    attr_dict = {
        a["key"]: a["value"] for a in response_json["attributes"]
    }
    assert attr_dict["project_type"] == "RNA-Seq"
    assert attr_dict["pi"] == "Dr. Smith"
    assert attr_dict["xpress_project_id"] == "12345"


def test_patch_project_empty_attributes_is_noop(
    client: TestClient, session: Session
):
    """Test that PATCH with empty attributes list is a no-op"""
    new_project = Project(name="Test Project", created_by="testuser")
    new_project.project_id = generate_project_id(session=session)
    new_project.attributes = [
        ProjectAttribute(key="Department", value="R&D"),
        ProjectAttribute(key="Priority", value="High"),
    ]
    session.add(new_project)
    session.commit()

    update_data = {"attributes": []}
    response = client.patch(
        f"/api/v1/projects/{new_project.project_id}",
        json=update_data,
    )

    assert response.status_code == 200
    response_json = response.json()

    assert len(response_json["attributes"]) == 2
    attr_dict = {
        a["key"]: a["value"] for a in response_json["attributes"]
    }
    assert attr_dict["Department"] == "R&D"
    assert attr_dict["Priority"] == "High"


def test_patch_project_name_only(
    client: TestClient, session: Session
):
    """Test that PATCH can update name without touching attributes"""
    new_project = Project(name="Original Name", created_by="testuser")
    new_project.project_id = generate_project_id(session=session)
    new_project.attributes = [
        ProjectAttribute(key="Department", value="R&D"),
    ]
    session.add(new_project)
    session.commit()

    update_data = {"name": "Updated Name"}
    response = client.patch(
        f"/api/v1/projects/{new_project.project_id}",
        json=update_data,
    )

    assert response.status_code == 200
    response_json = response.json()
    assert response_json["name"] == "Updated Name"
    assert len(response_json["attributes"]) == 1
    assert response_json["attributes"][0]["key"] == "Department"
    assert response_json["attributes"][0]["value"] == "R&D"


def test_patch_project_not_found(client: TestClient):
    """Test that PATCH on a non-existent project returns 404"""
    update_data = {"name": "New Name"}
    response = client.patch(
        "/api/v1/projects/nonexistent-project-id",
        json=update_data,
    )
    assert response.status_code == 404
    assert "not found" in response.json()["detail"].lower()


def test_patch_project_duplicate_attribute_keys(
    client: TestClient, session: Session
):
    """Test that PATCH with duplicate attribute keys fails"""
    new_project = Project(name="Test Project", created_by="testuser")
    new_project.project_id = generate_project_id(session=session)
    new_project.attributes = []
    session.add(new_project)
    session.commit()

    update_data = {
        "attributes": [
            {"key": "Priority", "value": "High"},
            {"key": "Priority", "value": "Low"},
        ]
    }
    response = client.patch(
        f"/api/v1/projects/{new_project.project_id}",
        json=update_data,
    )

    assert response.status_code == 400
    assert "duplicate" in response.json()["detail"].lower()


def test_patch_project_case_insensitive_duplicate_attribute_keys(
    client: TestClient, session: Session
):
    """Test that PATCH with attribute keys differing only in case returns 400."""
    new_project = Project(name="Test Project", created_by="testuser")
    new_project.project_id = generate_project_id(session=session)
    new_project.attributes = []
    session.add(new_project)
    session.commit()

    update_data = {
        "attributes": [
            {"key": "Priority", "value": "High"},
            {"key": "priority", "value": "Low"},
        ]
    }
    response = client.patch(
        f"/api/v1/projects/{new_project.project_id}",
        json=update_data,
    )
    assert response.status_code == 400
    assert "duplicate" in response.json()["detail"].lower()


def test_patch_project_upserts_attribute_case_insensitively(
    client: TestClient, session: Session
):
    """Test that PATCH matches existing attributes case-insensitively
    and updates the value without creating a duplicate."""
    new_project = Project(name="Test Project", created_by="testuser")
    new_project.project_id = generate_project_id(session=session)
    new_project.attributes = [
        ProjectAttribute(key="Department", value="R&D"),
    ]
    session.add(new_project)
    session.commit()

    # Patch with different casing — should update existing, not create duplicate
    update_data = {
        "attributes": [
            {"key": "department", "value": "Engineering"},
        ]
    }
    response = client.patch(
        f"/api/v1/projects/{new_project.project_id}",
        json=update_data,
    )
    assert response.status_code == 200
    attrs = response.json()["attributes"]
    assert len(attrs) == 1
    assert attrs[0]["key"] == "department"
    assert attrs[0]["value"] == "Engineering"


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
    assert response_json["status"] == "SUBMITTED"
    assert response_json["user"] == "testuser"

    # Verify AWS Batch was called with correct parameters
    mock_batch.submit_job.assert_called_once()
    call_args = mock_batch.submit_job.call_args[1]
    assert call_args["jobQueue"] == "batch-queue"
    assert call_args["jobDefinition"] == "pipeline-job-def:1"


NGS360_PIPELINE_CONFIG = {
    "project_type": "RNA-Seq",
    "project_admins": ["admin@example.com"],
    "platforms": {
        "Arvados": {
            "create_project_command": "arvados loadProject -p {{projectid}}",
        },
        "NGS360": {
            "create_project_command": "samples generate --projectid {{projectid}}",
            "references": [
                {"RNA-Seq: GRCh38ERCC.ensembl91": "GRCh38ERCC.ensembl91"},
            ],
            # What to launch is added by _config_launching_workflow, which needs
            # a registered workflow to name
            "aws_batch": {
                "launch-pipeline": {
                    # For a command; a launch runs where its workflow is deployed
                    "job_definition": "not-for-a-launch:1",
                    "environment": [{"name": "WES_API_ENDPOINT", "value": "https://wes"}],
                },
            },
        },
    },
    "aws_batch": {
        "job_name": "{{action}}-{{projectid}}",
        "job_definition": "ngs360-backend",
        "job_queue": "batch-queue",
        "command": "unused",
        "environment": [{"name": "PROJECT", "value": "{{projectid}}"}],
    },
}


def _submit_action(client, project, mock_s3_client, body, config=None):
    """Submit an action against a pipeline config offering the NGS360 platform"""
    mock_s3_client.setup_bucket(
        "ngs360-resources", "pipeline_configs/",
        [{"Key": "pipeline_configs/rna-seq_pipeline.yaml"}], []
    )
    mock_s3_client.uploaded_files["ngs360-resources"] = {
        "pipeline_configs/rna-seq_pipeline.yaml":
            yaml.dump(config or NGS360_PIPELINE_CONFIG).encode("utf-8")
    }
    return client.post(
        f"/api/v1/projects/{project.project_id}/actions/submit",
        json={"project_type": "RNA-Seq", **body}
    )


def _mock_batch(mock_boto_client: MagicMock) -> MagicMock:
    """A mocked AWS Batch client that accepts any job"""
    mock_batch = MagicMock()
    mock_batch.submit_job.return_value = {"jobId": "aws-batch-job-123"}
    mock_boto_client.return_value = mock_batch
    return mock_batch


def _batch_environment(mock_batch: MagicMock) -> dict:
    """The environment a mocked submit_job was called with, as a dict"""
    overrides = mock_batch.submit_job.call_args[1]["containerOverrides"]
    return {env["name"]: env["value"] for env in overrides["environment"]}


LAUNCH = {
    "action": "launch-pipeline",
    "platform": "NGS360",
    "reference": "RNA-Seq: GRCh38ERCC.ensembl91",
}

BATCH_ENGINE = "AWSBatch"
OTHER_ENGINE = "AWSHealthOmics (us-east)"

LAUNCHER_INPUTS = [
    {"id": "sample_sheet", "type": "File", "required": True},
    {"id": "reference_model", "type": "string", "required": True},
    {"id": "platform", "type": "string?", "required": False},
    {"id": "project_id", "type": "string?", "required": False},
    {"id": "run_fusion", "type": "boolean?", "required": False},
]


@pytest.fixture(name="launcher")
def launcher_fixture(session: Session) -> Workflow:
    """
    A launcher workflow with versions 1-3 and `stable` pointing at version 1.

    Versions 1 and 2 are deployed on the Batch engine, each naming its own job
    definition. Version 3 -- the latest, so what a bare id means -- is deployed
    on another engine only, so launching it has to be refused.
    """
    session.add(Platform(name=BATCH_ENGINE))
    session.add(Platform(name=OTHER_ENGINE))
    workflow = Workflow(name="RNA-Seq Launcher", created_by="testuser")
    session.add(workflow)
    session.flush()
    for number in (1, 2, 3):
        version = WorkflowVersion(
            workflow_id=workflow.id, version=number,
            definition_uri=f"s3://definitions/launcher-v{number}.cwl",
            inputs=LAUNCHER_INPUTS, created_by="testuser",
        )
        session.add(version)
        session.flush()
        session.add(WorkflowDeployment(
            workflow_version_id=version.id,
            engine=BATCH_ENGINE if number < 3 else OTHER_ENGINE,
            external_id=f"runner:{number}" if number < 3 else "arn:aws:omics:workflow/3",
            created_by="testuser",
        ))
        if number == 1:
            session.add(WorkflowVersionAlias(
                workflow_id=workflow.id, alias="stable",
                workflow_version_id=version.id, created_by="testuser",
            ))
    session.commit()
    return workflow


def _config_launching_workflow(workflow: Workflow, tag: str = ":2", **changes) -> dict:
    """The NGS360 pipeline config, with the platform launching a registered workflow"""
    config = copy.deepcopy(NGS360_PIPELINE_CONFIG)
    config["platforms"]["NGS360"]["launch_workflow"] = {
        "workflow": f"{workflow.id}{tag}",
        "engine": BATCH_ENGINE,
        "inputs": {
            "platform": "NGS360",
            "project_id": "{{projectid}}",
            "reference_model": "{{reference}}",
            "sample_sheet": {
                "class": "File",
                "location": "s3://store/{{projectid}}/{{projectid}}.{{project_type}}.txt",
            },
        },
        **changes,
    }
    return config


def _launch_inputs(mock_s3_client, command: list[str]) -> dict:
    """The inputs object a workflow launch wrote, read from where its command points"""
    assert command[0] == "--workflow" and command[2] == "--inputs"
    bucket, key = command[3].removeprefix("s3://").split("/", 1)
    return json.loads(mock_s3_client.uploaded_files[bucket][key])


@patch("api.jobs.services.boto3.client")
@patch("api.actions.services.get_setting_value")
def test_submit_other_action_ignores_launch_job_settings(
    mock_get_setting: MagicMock,
    mock_boto_client: MagicMock,
    client: TestClient,
    test_project: Project,
    mock_s3_client
):
    """Test an action with no settings of its own runs in the project type's job definition"""
    mock_get_setting.return_value = "s3://ngs360-resources/pipeline_configs/"
    mock_batch = _mock_batch(mock_boto_client)

    response = _submit_action(client, test_project, mock_s3_client, {
        "action": "create-project",
        "platform": "NGS360",
    })

    assert response.status_code == 201
    call_args = mock_batch.submit_job.call_args[1]
    assert call_args["jobDefinition"] == "ngs360-backend"
    names = [env["name"] for env in call_args["containerOverrides"]["environment"]]
    assert "WES_API_ENDPOINT" not in names


@pytest.mark.parametrize("reference", [None, "RNA-Seq: GRCm38ERCC.ensembl91"])
@patch("api.jobs.services.boto3.client")
@patch("api.actions.services.get_setting_value")
def test_submit_launch_pipeline_job_requires_configured_reference(
    mock_get_setting: MagicMock,
    mock_boto_client: MagicMock,
    reference,
    client: TestClient,
    test_project: Project,
    launcher: Workflow,
    mock_s3_client
):
    """Test a launch can only name a reference model the platform lists"""
    mock_get_setting.return_value = "s3://ngs360-resources/pipeline_configs/"
    mock_batch = _mock_batch(mock_boto_client)

    response = _submit_action(
        client, test_project, mock_s3_client,
        {"action": "launch-pipeline", "platform": "NGS360", "reference": reference},
        _config_launching_workflow(launcher),
    )

    assert response.status_code == 400
    assert "Reference" in response.json()["detail"]
    mock_batch.submit_job.assert_not_called()


@patch("api.jobs.services.boto3.client")
@patch("api.actions.services.get_setting_value")
def test_submit_launch_pipeline_job_on_platform_that_cannot_launch(
    mock_get_setting: MagicMock,
    mock_boto_client: MagicMock,
    client: TestClient,
    test_project: Project,
    mock_s3_client
):
    """Test launching is refused on a platform that names no workflow to launch"""
    mock_get_setting.return_value = "s3://ngs360-resources/pipeline_configs/"
    mock_batch = _mock_batch(mock_boto_client)

    response = _submit_action(client, test_project, mock_s3_client, {
        "action": "launch-pipeline",
        "platform": "Arvados",
        "reference": "RNA-Seq: GRCh38ERCC.ensembl91",
    })

    assert response.status_code == 400
    mock_batch.submit_job.assert_not_called()


@patch("api.jobs.services.boto3.client")
@patch("api.actions.services.get_setting_value")
def test_submit_launch_runs_registered_workflow(
    mock_get_setting: MagicMock,
    mock_boto_client: MagicMock,
    client: TestClient,
    test_project: Project,
    launcher: Workflow,
    mock_s3_client
):
    """Test a launch runs the configured workflow version with a runner job"""
    mock_get_setting.return_value = "s3://ngs360-resources/pipeline_configs/"
    mock_batch = _mock_batch(mock_boto_client)

    response = _submit_action(
        client, test_project, mock_s3_client,
        {
            **LAUNCH,
            # project_id is the configuration's to set, whatever the request says
            "inputs": {"run_fusion": True, "project_id": "P-SOMEONE-ELSES", "platform": None},
        },
        _config_launching_workflow(launcher),
    )

    assert response.status_code == 201, response.text
    call_args = mock_batch.submit_job.call_args[1]
    command = call_args["containerOverrides"]["command"]
    # The runner is told where the definition and the inputs are, nothing more
    assert command[:3] == ["--workflow", "s3://definitions/launcher-v2.cwl", "--inputs"]
    assert f"/project/{test_project.project_id}/launch_inputs/" in command[3]
    assert command[3].endswith(".inputs.json")
    assert _launch_inputs(mock_s3_client, command) == {
        "run_fusion": True,
        "platform": "NGS360",
        "project_id": test_project.project_id,
        # The reference label, resolved to the configured reference model
        "reference_model": "GRCh38ERCC.ensembl91",
        "sample_sheet": {
            "class": "File",
            "location": (
                f"s3://store/{test_project.project_id}/{test_project.project_id}.RNA-Seq.txt"
            ),
        },
    }
    # The job definition is the version's deployment on the engine, whatever
    # the action's aws_batch settings name
    assert call_args["jobDefinition"] == "runner:2"
    # Not overridden, so the project type's queue still applies
    assert call_args["jobQueue"] == "batch-queue"
    # The action's environment is added to the project type's
    environment = _batch_environment(mock_batch)
    assert environment["PROJECT"] == test_project.project_id
    assert environment["WES_API_ENDPOINT"] == "https://wes"

    # The inputs are kept with the project's files
    files = client.get(
        "/api/v1/files", params={"uri": command[3]}
    ).json()["data"]
    assert [f["uri"] for f in files] == [command[3]]


@pytest.mark.parametrize("tag, definition, job_definition", [
    (":1", "s3://definitions/launcher-v1.cwl", "runner:1"),
    (":stable", "s3://definitions/launcher-v1.cwl", "runner:1"),
    (":2", "s3://definitions/launcher-v2.cwl", "runner:2"),
])
@patch("api.jobs.services.boto3.client")
@patch("api.actions.services.get_setting_value")
def test_submit_launch_runs_the_workflow_version_the_config_names(
    mock_get_setting: MagicMock,
    mock_boto_client: MagicMock,
    tag: str,
    definition: str,
    job_definition: str,
    client: TestClient,
    test_project: Project,
    launcher: Workflow,
    mock_s3_client
):
    """Test the workflow reference picks the version by number or by alias"""
    mock_get_setting.return_value = "s3://ngs360-resources/pipeline_configs/"
    mock_batch = _mock_batch(mock_boto_client)

    response = _submit_action(
        client, test_project, mock_s3_client, LAUNCH, _config_launching_workflow(launcher, tag)
    )

    assert response.status_code == 201, response.text
    call_args = mock_batch.submit_job.call_args[1]
    assert call_args["containerOverrides"]["command"][1] == definition
    assert call_args["jobDefinition"] == job_definition


@patch("api.jobs.services.boto3.client")
@patch("api.actions.services.get_setting_value")
def test_submit_launch_prefers_the_version_recorded_for_the_project(
    mock_get_setting: MagicMock,
    mock_boto_client: MagicMock,
    client: TestClient,
    session: Session,
    test_project: Project,
    launcher: Workflow,
    mock_s3_client
):
    """Test a version recorded for the project is launched whatever the config names"""
    mock_get_setting.return_value = "s3://ngs360-resources/pipeline_configs/"
    mock_batch = _mock_batch(mock_boto_client)
    session.add(ProjectWorkflowVersion(
        project_id=test_project.project_id, workflow_id=launcher.id, version=1,
        created_by="testuser",
    ))
    session.commit()

    response = _submit_action(
        client, test_project, mock_s3_client, LAUNCH, _config_launching_workflow(launcher, ":2")
    )

    assert response.status_code == 201, response.text
    call_args = mock_batch.submit_job.call_args[1]
    assert call_args["containerOverrides"]["command"][1] == "s3://definitions/launcher-v1.cwl"
    assert call_args["jobDefinition"] == "runner:1"


@patch("api.jobs.services.boto3.client")
@patch("api.actions.services.get_setting_value")
def test_submit_launch_refuses_a_version_not_deployed_on_the_engine(
    mock_get_setting: MagicMock,
    mock_boto_client: MagicMock,
    client: TestClient,
    test_project: Project,
    launcher: Workflow,
    mock_s3_client
):
    """Test the latest version, deployed only on another engine, cannot be launched"""
    mock_get_setting.return_value = "s3://ngs360-resources/pipeline_configs/"
    mock_batch = _mock_batch(mock_boto_client)

    response = _submit_action(
        client, test_project, mock_s3_client, LAUNCH,
        _config_launching_workflow(launcher, tag=""),
    )

    assert response.status_code == 400
    assert response.json()["detail"] == (
        f"Version 3 of workflow {launcher.id} is not deployed on '{BATCH_ENGINE}'"
    )
    mock_batch.submit_job.assert_not_called()


@pytest.mark.parametrize("inputs, config_inputs, detail", [
    ({"run_fuson": True}, None, "has no input named: run_fuson"),
    # The configuration stops supplying the sample sheet, and the request has none
    ({}, {"reference_model": "{{reference}}"}, "requires a value for: sample_sheet"),
])
@patch("api.jobs.services.boto3.client")
@patch("api.actions.services.get_setting_value")
def test_submit_launch_checks_inputs_against_the_workflow_version(
    mock_get_setting: MagicMock,
    mock_boto_client: MagicMock,
    inputs: dict,
    config_inputs: dict | None,
    detail: str,
    client: TestClient,
    test_project: Project,
    launcher: Workflow,
    mock_s3_client
):
    """Test an unknown input or a missing required one is refused before anything is written"""
    mock_get_setting.return_value = "s3://ngs360-resources/pipeline_configs/"
    mock_batch = _mock_batch(mock_boto_client)
    changes = {} if config_inputs is None else {"inputs": config_inputs}

    response = _submit_action(
        client, test_project, mock_s3_client, {**LAUNCH, "inputs": inputs},
        _config_launching_workflow(launcher, **changes),
    )

    assert response.status_code == 400
    assert response.json()["detail"] == f"Version 2 of workflow {launcher.id} {detail}"
    mock_batch.submit_job.assert_not_called()
    assert list(mock_s3_client.uploaded_files) == ["ngs360-resources"]


@patch("api.jobs.services.boto3.client")
@patch("api.actions.services.get_setting_value")
def test_submit_launch_takes_the_reference_as_an_input_where_none_are_listed(
    mock_get_setting: MagicMock,
    mock_boto_client: MagicMock,
    client: TestClient,
    test_project: Project,
    launcher: Workflow,
    mock_s3_client
):
    """Test a platform listing no references needs no reference label for a launch"""
    mock_get_setting.return_value = "s3://ngs360-resources/pipeline_configs/"
    mock_batch = _mock_batch(mock_boto_client)
    config = _config_launching_workflow(launcher)
    ngs360 = config["platforms"]["NGS360"]
    del ngs360["references"]
    del ngs360["launch_workflow"]["inputs"]["reference_model"]

    response = _submit_action(
        client, test_project, mock_s3_client,
        {
            "action": "launch-pipeline",
            "platform": "NGS360",
            "inputs": {"reference_model": "GRCm38ERCC.ensembl91"},
        },
        config,
    )

    assert response.status_code == 201, response.text
    command = mock_batch.submit_job.call_args[1]["containerOverrides"]["command"]
    assert _launch_inputs(mock_s3_client, command)["reference_model"] == "GRCm38ERCC.ensembl91"


def _config_minting_launch_key(workflow: Workflow, hours: int = 72) -> dict:
    """The NGS360 pipeline config, with the launch action asking for a user API key"""
    config = _config_launching_workflow(workflow)
    launch = config["platforms"]["NGS360"]["aws_batch"]["launch-pipeline"]
    launch["user_api_key_hours"] = hours
    return config


@patch("api.jobs.services.boto3.client")
@patch("api.actions.services.get_setting_value")
def test_submit_launch_mints_submitter_api_key(
    mock_get_setting: MagicMock,
    mock_boto_client: MagicMock,
    client: TestClient,
    session: Session,
    test_project: Project,
    launcher: Workflow,
    mock_s3_client
):
    """Test an action asking for a key gets one owned by the submitter, named for the job"""
    from api.auth.models import APIKey, User
    from core.security import hash_api_key

    mock_get_setting.return_value = "s3://ngs360-resources/pipeline_configs/"
    mock_batch = _mock_batch(mock_boto_client)

    before = datetime.now(timezone.utc)
    response = _submit_action(
        client, test_project, mock_s3_client, LAUNCH, _config_minting_launch_key(launcher, 72)
    )

    assert response.status_code == 201
    environment = _batch_environment(mock_batch)
    (api_key,) = session.exec(select(APIKey)).all()
    assert api_key.hashed_key == hash_api_key(environment["NGS360_AUTH_TOKEN"])
    # The key reaches the job through its environment and is not among the
    # inputs written to the project's files
    command = mock_batch.submit_job.call_args[1]["containerOverrides"]["command"]
    launch_inputs = json.dumps(_launch_inputs(mock_s3_client, command))
    assert environment["NGS360_AUTH_TOKEN"] not in launch_inputs
    # The job is not told its key's id: the key is retired from here when the
    # job ends, not by the job.
    assert "NGS360_AUTH_KEY_ID" not in environment
    assert session.get(User, api_key.user_id).username == "testuser"
    assert api_key.is_active
    assert api_key.name == "Batch job aws-batch-job-123"
    expires_at = api_key.expires_at.replace(tzinfo=timezone.utc)
    ttl = timedelta(hours=72)
    assert before + ttl <= expires_at <= datetime.now(timezone.utc) + ttl


@pytest.mark.parametrize("body", [
    LAUNCH,                                               # launch not asking for a key
    {"action": "create-project", "platform": "NGS360"},  # another action, same platform
])
@patch("api.jobs.services.boto3.client")
@patch("api.actions.services.get_setting_value")
def test_submit_action_not_asking_for_a_key_mints_nothing(
    mock_get_setting: MagicMock,
    mock_boto_client: MagicMock,
    body,
    client: TestClient,
    session: Session,
    test_project: Project,
    launcher: Workflow,
    mock_s3_client
):
    """Test only the action whose settings ask for a key is given a credential"""
    from api.auth.models import APIKey

    mock_get_setting.return_value = "s3://ngs360-resources/pipeline_configs/"
    mock_batch = _mock_batch(mock_boto_client)

    # create-project runs against a config where launch does ask for a key
    config = (
        _config_launching_workflow(launcher) if body is LAUNCH
        else _config_minting_launch_key(launcher)
    )
    response = _submit_action(client, test_project, mock_s3_client, body, config)

    assert response.status_code == 201
    environment = _batch_environment(mock_batch)
    assert "NGS360_AUTH_TOKEN" not in environment
    assert "NGS360_AUTH_KEY_ID" not in environment
    assert session.exec(select(APIKey)).all() == []


@patch("api.jobs.services.boto3.client")
@patch("api.actions.services.get_setting_value")
def test_submit_launch_failure_revokes_minted_key(
    mock_get_setting: MagicMock,
    mock_boto_client: MagicMock,
    client: TestClient,
    session: Session,
    test_project: Project,
    launcher: Workflow,
    mock_s3_client
):
    """Test a key minted for a job AWS Batch refused does not stay usable"""
    from api.auth.models import APIKey

    mock_get_setting.return_value = "s3://ngs360-resources/pipeline_configs/"
    mock_batch = MagicMock()
    mock_batch.submit_job.side_effect = botocore.exceptions.ClientError(
        {"Error": {"Code": "ClientException", "Message": "no such queue"}}, "SubmitJob"
    )
    mock_boto_client.return_value = mock_batch

    response = _submit_action(
        client, test_project, mock_s3_client, LAUNCH, _config_minting_launch_key(launcher)
    )

    assert response.status_code == 500
    (api_key,) = session.exec(select(APIKey)).all()
    session.refresh(api_key)
    assert not api_key.is_active
    assert api_key.revoked_at is not None


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

    # The job is attributed to the project it was submitted under
    assert response.json()["project_id"] == test_project.project_id


@patch("api.jobs.services.boto3.client")
@patch("api.project.services.get_setting")
def test_ingest_vendor_data(
    mock_get_setting: MagicMock,
    mock_boto_client: MagicMock,
    client: TestClient,
    test_project: Project,
    mock_s3_client
):
    """Test the ingest vendor data endpoint"""
    # Set up test parameters
    # Set up supporting mocks
    from api.settings.models import Setting
    mock_get_setting.return_value = Setting(value="s3://config_bucket/configs/vendor_ingestion.yaml")

    mock_batch = MagicMock()
    mock_batch.submit_job.return_value = {
        "jobId": "aws-batch-job-123",
        "jobName": "aws-batch-job-123",
    }
    mock_boto_client.return_value = mock_batch

    vendor_ingestion_config = {
        "inputs": [
            {
                "name": "bucket",
                "desc": "S3 Bucket Name/Prefix where the data to be ingested is located.",
                "type": "String",
                "required": True
            },
            {
                "name": "projectid",
                "desc": "Project ID",
                "type": "String",
                "required": True
            },
            {
                "name": "manifest_uri",
                "desc": "S3 URI for the manifest file containing the list of files to ingest.",
                "type": "String",
                "required": True
            },
            {
                "name": "user",
                "desc": "User submitting the ingestion job.",
                "type": "String",
                "required": True
            }
        ],
        "aws_batch": {
            "job_name": "Ingest Vendor Data - {{ projectid }} - {{ bucket }}",
            "job_definition": "aws_job_def",
            "job_queue": "batch-job-queue",
            "command": "-b {{ bucket }} -p {{ projectid }}"
        }
    }

    files = [{"Key": "configs/vendor_ingestion.yaml"}]
    mock_s3_client.setup_bucket("config_bucket", "configs/", files, [])
    mock_s3_client.uploaded_files["config_bucket"] = {
        "configs/vendor_ingestion.yaml": yaml.dump(vendor_ingestion_config).encode("utf-8")
    }

    # Test
    response = client.post(
        f"/api/v1/projects/{test_project.project_id}/ingest?"
        "files_uri=s3://vendor-data-bucket/incoming/project123&"
        "manifest_uri=s3://vendor-data-bucket/project123/manifest.csv"
    )
    # Check results
    assert response.status_code == 201
    response_json = response.json()
    assert response_json["id"] == "aws-batch-job-123"


# ---------------------------------------------------------------------------
# Project.restricted is settable through the API
# ---------------------------------------------------------------------------
#
# Added 2026-10-13. The field has been on ProjectUpdate since the flag was
# introduced in #425, and neither update_project nor patch_project persisted
# it, so a request setting it returned 200 and changed nothing. An ignored
# field is indistinguishable from an applied one in the response, which is why
# it went unnoticed for five weeks.
#
# It also made "0 of 11,156 projects are restricted" misleading. That figure
# was quoted repeatedly as evidence that nobody wanted restricted projects
# while the open-by-default download policy was argued; it actually meant
# nobody could create one. Found by trying to set it in production in order to
# prove the membership gate.


def _project(session: Session, name: str = "Restrictable") -> Project:
    project = Project(name=name, created_by="testuser")
    project.project_id = generate_project_id(session=session)
    session.add(project)
    session.commit()
    session.refresh(project)
    return project


def test_patch_can_restrict_a_project(client: TestClient, session: Session):
    project = _project(session)
    assert project.restricted is False

    response = client.patch(
        f"/api/v1/projects/{project.project_id}", json={"restricted": True}
    )

    assert response.status_code == 200
    assert response.json()["restricted"] is True
    session.refresh(project)
    assert project.restricted is True, (
        "the response said 200 but nothing was written -- this is the bug this "
        "test exists for, not a stale assertion"
    )


def test_unrestricting_needs_membership_and_enrolment_is_the_way_in(
    superuser_client: TestClient, session: Session
):
    """
    The recovery path, in full, because it is two steps and not obvious.

    Every project-plane route applies the membership gate, `PATCH` included --
    so a restricted project cannot be unlocked by someone who is not a member.
    That is a one-way door unless something is exempt, and if nothing is, a
    project restricted with nobody in it is unreachable through the API
    entirely, including to an administrator. This was found by restricting a
    real project in production and discovering there was no way back.

    What is exempt is `project:manage_members`, because membership *is* the
    restriction's allowlist and managing the allowlist cannot require being on
    it. So the way in is: enrol, then act. It leaves a `project_member` row
    behind, which is the point -- an administrator reaching into a locked-down
    project should leave a trace.
    """
    from api.rbac.seed import sync_rbac_catalog

    # The superuser fixture holds no grant, so it does not seed the builtin
    # catalog the way the ordinary client fixture does -- and project_owner has
    # to exist to be granted.
    sync_rbac_catalog(session)

    project = _project(session)
    project.restricted = True
    session.add(project)
    session.commit()

    # Step 0: refused, even as a superuser, because membership is the gate and
    # the superuser flag deliberately does not short-circuit it.
    assert superuser_client.patch(
        f"/api/v1/projects/{project.project_id}", json={"restricted": False}
    ).status_code == 403

    # Step 1: enrol. Permitted on a restricted project by design -- and note
    # the actor needs project:manage_members to do it, which is `critical` and
    # so held by admins rather than by an ordinary authenticated caller.
    assert superuser_client.post(
        f"/api/v1/projects/{project.project_id}/members",
        json={"username": "admin", "role": "project_owner"},
    ).status_code in (200, 201)

    # Step 2: now a member, so the project is reachable again.
    response = superuser_client.patch(
        f"/api/v1/projects/{project.project_id}", json={"restricted": False}
    )
    assert response.status_code == 200, response.text
    session.refresh(project)
    assert project.restricted is False


def test_put_can_restrict_a_project(client: TestClient, session: Session):
    project = _project(session)

    response = client.put(
        f"/api/v1/projects/{project.project_id}",
        json={"name": project.name, "restricted": True},
    )

    assert response.status_code == 200
    session.refresh(project)
    assert project.restricted is True


def test_omitting_restricted_leaves_it_alone(client: TestClient, session: Session):
    """
    `None` means "not supplied", not "set to false" -- otherwise any client
    patching an attribute would silently unlock the project.
    """
    project = _project(session)
    project.restricted = True
    session.add(project)
    session.commit()
    # Enrolled directly, so the membership gate is satisfied and this test is
    # about the None semantics rather than about the gate.
    from sqlmodel import select as _select

    from api.auth.models import User
    from api.rbac.models import GrantSource, ProjectMember, Role

    user = session.exec(_select(User).where(User.username == "testuser")).one()
    role = session.exec(_select(Role).where(Role.name == "project_owner")).one()
    session.add(ProjectMember(project_id=project.id, user_id=user.id,
                              role_id=role.id, source=GrantSource.MANUAL))
    session.commit()

    response = client.patch(
        f"/api/v1/projects/{project.project_id}",
        json={"attributes": [{"key": "pi", "value": "Dr. Smith"}]},
    )

    assert response.status_code == 200, response.text
    session.refresh(project)
    assert project.restricted is True


def test_a_project_can_be_created_already_restricted(
    client: TestClient, session: Session
):
    """
    Creating it open and closing it in a second request leaves a window in
    which it is readable, which is the thing someone asking for a restricted
    project is trying to avoid.
    """
    response = client.post(
        "/api/v1/projects", json={"name": "Locked", "restricted": True}
    )

    assert response.status_code == 201, response.text
    assert response.json()["restricted"] is True

    from sqlmodel import select as _select

    project = session.exec(
        _select(Project).where(
            Project.project_id == response.json()["project_id"]
        )
    ).one()
    assert project.restricted is True


def test_a_project_is_created_unrestricted_by_default(client: TestClient):
    response = client.post("/api/v1/projects", json={"name": "Open"})

    assert response.status_code == 201, response.text
    assert response.json()["restricted"] is False
