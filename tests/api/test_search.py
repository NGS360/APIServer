'''
Test /search endpoint
'''

from fastapi.testclient import TestClient
from opensearchpy import OpenSearch

def test_search_projects(client: TestClient, opensearch_client: OpenSearch):
    ''' Test that we can search for projects '''
    # Test No projects, this also ensure we are using the test db
    response = client.get('/api/v1/search?query=AI&index=projects')
    assert response.status_code == 200
    assert response.json() == {'items': [], 'total': 0, 'page': 1, 'per_page': 20}

    # Add a project to search for
    new_project = {
        "name": "AI Research",
        "attributes": [
            {"key": "description", "value": "Exploring AI techniques"},
            {"key": "Department", "value": "R&D"},
            {"key": "Priority", "value": "High"}
        ]
    }

    response = client.post('/api/v1/projects', json=new_project)
    assert response.status_code == 201

    # Now search for the project
    response = client.get('/api/v1/search?query=AI&index=projects')
    assert response.status_code == 200
    response_json = response.json()

    # Check the data structure
    assert 'items' in response_json
    assert len(response_json['items']) == 1

    # Verify project details
    project = response_json['items'][0]
    assert project['name'] == 'AI Research'
