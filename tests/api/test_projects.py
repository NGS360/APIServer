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
