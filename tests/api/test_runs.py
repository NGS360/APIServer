'''
Test /runs endpoint
'''
from fastapi.testclient import TestClient
from sqlmodel import Session

def test_get_runs(client: TestClient, session: Session):
    ''' Test that we can get all runs '''
    # Test No projects, this also ensure we are using the test db
    response = client.get('/api/v1/runs')
    assert response.status_code == 200
    assert response.json() == {
        'data': [],
        'total_items': 0,
        'total_pages': 0,
        'current_page': 1,
        'per_page': 20,
        'has_next': False,
        'has_prev': False
    }
