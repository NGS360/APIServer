from fastapi.testclient import TestClient


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
