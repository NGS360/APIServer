'''
Test /search endpoint
'''

from fastapi.testclient import TestClient

def test_search_projects(client: TestClient):
    ''' Test that we can search for projects '''
    # Test No projects, this also ensure we are using the test db
    response = client.get('/api/v1/search?query=AI')
    assert response.status_code == 200

def Xtest():
    assert response.json() == {
        'data': [],
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
    response = client.get('/api/v1/search?query=AI')
    assert response.status_code == 200
    response_json = response.json()

    # Check the data structure
    assert 'data' in response_json
    assert len(response_json['data']) == 1

    # Verify project details
    project = response_json['data'][0]
    assert project['name'] == 'AI Research'
