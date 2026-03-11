from fastapi.testclient import TestClient
from sqlmodel import Session
from api.workflow.models import Workflow, WorkflowAttribute


def test_get_workflows(client: TestClient, session: Session):
    """Test retrieving a list of workflows"""
    workflow = Workflow(
        name="Test Workflow",
        definition_uri="s3://my-bucket/workflows/test-workflow.zip",
        created_by="testuser",
    )
    session.add(workflow)
    session.flush()
    workflow_attribute = WorkflowAttribute(
        workflow_id=workflow.id,
        key="version",
        value="1"
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
    assert wf["definition_uri"] == "s3://my-bucket/workflows/test-workflow.zip"
    assert wf["created_by"] == "testuser"
    assert "version" in wf
    assert "registrations" in wf


def test_get_workflow_by_id(client: TestClient, session: Session):
    """Test retrieving a workflow by its ID"""
    workflow = Workflow(
        name="Test Workflow",
        definition_uri="s3://my-bucket/workflows/test-workflow.zip",
        created_by="testuser",
    )
    session.add(workflow)
    session.flush()
    workflow_attribute = WorkflowAttribute(
        workflow_id=workflow.id,
        key="version",
        value="1"
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
        'definition_uri': "s3://my-bucket/workflows/image-classification.zip",
        'attributes': [
            {'key': 'category', 'value': 'imaging'},
        ],
    }

    response = client.post("/api/v1/workflows", json=workflow_data)
    assert response.status_code == 201
    response_json = response.json()

    assert response_json["name"] == "Image Classification Workflow"
    assert response_json["definition_uri"] == "s3://my-bucket/workflows/image-classification.zip"
    assert response_json["created_by"] == "testuser"
    assert response_json["version"] is None
    assert "id" in response_json
    assert "created_at" in response_json


def test_post_workflow_with_version(client: TestClient):
    """Test posting a workflow with version"""
    workflow_data = {
        'name': 'RNA-Seq Alignment',
        'version': '2.1.0',
        'definition_uri': "s3://my-bucket/workflows/rnaseq-align.cwl",
    }

    response = client.post("/api/v1/workflows", json=workflow_data)
    assert response.status_code == 201
    response_json = response.json()

    assert response_json["name"] == "RNA-Seq Alignment"
    assert response_json["version"] == "2.1.0"
