from fastapi.testclient import TestClient
from sqlmodel import Session
from api.workflow.models import Workflow, WorkflowAttribute


def test_get_workflows(client: TestClient, session: Session):
    """Test retrieving a list of workflows"""
    workflow = Workflow(
        name="Test Workflow",
        created_by="testuser",
    )
    session.add(workflow)
    session.flush()
    workflow_attribute = WorkflowAttribute(
        workflow_id=workflow.id,
        key="category",
        value="genomics"
    )
    session.add(workflow_attribute)
    session.commit()

    response = client.get("/api/v1/workflows")
    assert response.status_code == 200
    response_json = response.json()

    # Validate response structure
    assert isinstance(response_json, list)
    assert len(response_json) == 1
    wf = response_json[0]
    assert wf["name"] == "Test Workflow"
    assert wf["created_by"] == "testuser"
    assert "versions" in wf
    assert "aliases" in wf


def test_get_workflow_by_id(client: TestClient, session: Session):
    """Test retrieving a workflow by its ID"""
    workflow = Workflow(
        name="Test Workflow",
        created_by="testuser",
    )
    session.add(workflow)
    session.flush()
    workflow_attribute = WorkflowAttribute(
        workflow_id=workflow.id,
        key="category",
        value="genomics"
    )
    session.add(workflow_attribute)
    session.commit()

    workflow_id = str(workflow.id)
    response = client.get(f"/api/v1/workflows/{workflow_id}")
    assert response.status_code == 200
    response_json = response.json()
    assert response_json["id"] == workflow_id
    assert response_json["name"] == "Test Workflow"
    assert response_json["created_by"] == "testuser"


def test_post_workflow(client: TestClient):
    """Test posting a new workflow"""
    workflow_data = {
        'name': 'Image Classification Workflow',
        'attributes': [
            {'key': 'category', 'value': 'imaging'},
        ],
    }

    response = client.post("/api/v1/workflows", json=workflow_data)
    assert response.status_code == 201
    response_json = response.json()

    assert response_json["name"] == "Image Classification Workflow"
    assert response_json["created_by"] == "testuser"
    assert "id" in response_json
    assert "created_at" in response_json
    assert response_json["versions"] is None or response_json["versions"] == []


def test_post_workflow_no_version_or_definition_uri(client: TestClient):
    """Workflow creation no longer accepts version or definition_uri."""
    workflow_data = {
        'name': 'RNA-Seq Alignment',
    }

    response = client.post("/api/v1/workflows", json=workflow_data)
    assert response.status_code == 201
    response_json = response.json()

    assert response_json["name"] == "RNA-Seq Alignment"
    # version and definition_uri are not on Workflow anymore
    assert "version" not in response_json
    assert "definition_uri" not in response_json


def test_get_workflow_by_id_invalid_uuid(client: TestClient):
    """An invalid (non-UUID) workflow_id must return 400, not 500."""
    response = client.get("/api/v1/workflows/not-a-uuid")
    assert response.status_code == 400
    assert "Invalid UUID format" in response.json()["detail"]


def test_get_workflow_by_id_nonexistent_uuid(client: TestClient):
    """A valid UUID that doesn't exist must return 404."""
    import uuid
    fake_id = str(uuid.uuid4())
    response = client.get(f"/api/v1/workflows/{fake_id}")
    assert response.status_code == 404
