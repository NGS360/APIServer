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
    assert response.json() == {
        'projects': [],  # Changed from 'data' to 'projects' for projects index
        'total_items': 0,
        'total_pages': 0,
        'current_page': 1,
        'per_page': 20,
        'has_next': False,
        'has_prev': False
    }

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

    # Check the data structure - now uses 'projects' key instead of 'data'
    assert 'projects' in response_json
    assert len(response_json['projects']) == 1
    assert response_json['total_items'] == 1
    assert response_json['total_pages'] == 1
    assert response_json['current_page'] == 1
    assert response_json['per_page'] == 20
    assert response_json['has_next'] == False
    assert response_json['has_prev'] == False

    # Verify project details
    project = response_json['projects'][0]  # Changed from 'data' to 'projects'
    assert project['name'] == 'AI Research'


def test_search_projects_with_dynamic_key(client: TestClient, opensearch_client: OpenSearch):
    ''' Test that projects search returns results under "projects" key '''
    # Add a project to search for
    new_project = {
        "name": "Machine Learning Project",
        "attributes": [
            {"key": "description", "value": "Advanced ML techniques"},
            {"key": "Department", "value": "AI Research"},
            {"key": "Priority", "value": "High"}
        ]
    }

    response = client.post('/api/v1/projects', json=new_project)
    assert response.status_code == 201

    # Search for the project
    response = client.get('/api/v1/search?query=Machine&index=projects')
    assert response.status_code == 200
    response_json = response.json()

    # Check that results are under "projects" key instead of "data"
    assert 'projects' in response_json
    assert 'data' not in response_json  # Should not have the old "data" key
    assert len(response_json['projects']) == 1
    assert response_json['total_items'] == 1
    assert response_json['total_pages'] == 1
    assert response_json['current_page'] == 1
    assert response_json['per_page'] == 20
    assert response_json['has_next'] == False
    assert response_json['has_prev'] == False

    # Verify project details
    project = response_json['projects'][0]
    assert project['name'] == 'Machine Learning Project'


def test_search_runs_index_uses_runs_key(client: TestClient, opensearch_client: OpenSearch):
    ''' Test that illumina_runs index search returns results under "illumina_runs" key (without creating actual illumina_runs) '''
    # Search the illumina_runs index (will be empty but should use correct key)
    response = client.get('/api/v1/search?query=test&index=illumina_runs')
    assert response.status_code == 200
    response_json = response.json()

    # Check that results are under "runs" key instead of "data"
    assert 'illumina_runs' in response_json
    assert 'data' not in response_json  # Should not have the old "data" key
    assert response_json['illumina_runs'] == []  # Empty results
    assert response_json['total_items'] == 0
    assert response_json['total_pages'] == 0
    assert response_json['current_page'] == 1
    assert response_json['per_page'] == 20
    assert response_json['has_next'] == False
    assert response_json['has_prev'] == False


def test_search_unknown_index_fallback(client: TestClient, opensearch_client: OpenSearch):
    ''' Test that unknown index still works with fallback to "data" key '''
    # Search with an unknown index
    response = client.get('/api/v1/search?query=test&index=unknown_index')
    assert response.status_code == 200
    response_json = response.json()

    # Should fallback to "data" key for unknown indexes
    assert 'data' in response_json
    assert response_json['data'] == []  # Empty results
    assert response_json['total_items'] == 0
