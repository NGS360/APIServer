"""
Test /projects endpoint

"""

from fastapi.testclient import TestClient
from sqlmodel import Session

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
