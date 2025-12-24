from fastapi.testclient import TestClient
from sqlmodel import Session
from api.workflow.models import Workflow, WorkflowAttribute


def test_get_workflows(client: TestClient, session: Session):
    """Test retrieving a list of workflows"""
    workflow = Workflow(
        name="Test Workflow",
        definition_uri="s3://my-bucket/workflows/test-workflow.zip",
        engine="TestEngine",
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


def test_get_workflow_by_id(client: TestClient, session: Session):
    ''' Test retrieving a workflow by its ID '''
    workflow = Workflow(
        name="Test Workflow",
        definition_uri="s3://my-bucket/workflows/test-workflow.zip",
        engine="TestEngine",
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


def test_post_workflow(client: TestClient):
    """Test posting a new workflow"""
    # Prepare workflow data
    workflow_data = {
        'name': 'Image Classification Workflow',
        'definition_uri': "s3://my-bucket/workflows/image-classification.zip",
        'engine': 'AWSHealthOmics',
        'attributes': [
            {'key': 'version', 'value': '1'},
        ],
    }

    # Post the new workflow
    response = client.post("/api/v1/workflows", json=workflow_data)
    assert response.status_code == 201
    response_json = response.json()

    # Validate response content
    assert response_json["name"] == "Image Classification Workflow"
