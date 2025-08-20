'''
Test /search endpoint - Multi-index search functionality
'''

from fastapi.testclient import TestClient
from opensearchpy import OpenSearch
import pytest

def test_multi_search_single_index(client: TestClient, opensearch_client: OpenSearch):
    '''Test multi-search with single index (backward compatibility)'''
    # Test empty search
    response = client.get('/api/v1/search?query=AI&indexes=projects')
    assert response.status_code == 200
    
    response_json = response.json()
    assert 'results' in response_json
    assert 'projects' in response_json['results']
    assert response_json['results']['projects']['total'] == 0
    assert response_json['results']['projects']['items'] == []
    assert response_json['total_across_indexes'] == 0
    assert response_json['partial_failure'] == False

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
    response = client.get('/api/v1/search?query=AI&indexes=projects')
    assert response.status_code == 200
    response_json = response.json()

    # Check the multi-search structure
    assert 'results' in response_json
    assert 'projects' in response_json['results']
    
    projects_result = response_json['results']['projects']
    assert projects_result['success'] == True
    assert projects_result['total'] == 1
    assert len(projects_result['items']) == 1
    assert projects_result['page'] == 1
    assert projects_result['per_page'] == 20
    assert projects_result['has_next'] == False
    assert projects_result['has_prev'] == False

    # Verify project details
    project = projects_result['items'][0]
    assert project['name'] == 'AI Research'
    assert project['index_name'] == 'projects'

def test_multi_search_multiple_indexes(client: TestClient, opensearch_client: OpenSearch):
    '''Test multi-search with multiple indexes'''
    # Search multiple indexes (even if some are empty)
    response = client.get('/api/v1/search?query=test&indexes=projects&indexes=samples&indexes=illumina_runs')
    assert response.status_code == 200
    
    response_json = response.json()
    assert 'results' in response_json
    assert len(response_json['results']) == 3
    assert 'projects' in response_json['results']
    assert 'samples' in response_json['results']
    assert 'illumina_runs' in response_json['results']
    
    # Check that each index has proper structure
    for index_name, result in response_json['results'].items():
        assert 'index_name' in result
        assert result['index_name'] == index_name
        assert 'items' in result
        assert 'total' in result
        assert 'page' in result
        assert 'per_page' in result
        assert 'has_next' in result
        assert 'has_prev' in result
        assert 'success' in result

def test_multi_search_pagination(client: TestClient, opensearch_client: OpenSearch):
    '''Test pagination in multi-search'''
    response = client.get('/api/v1/search?query=test&indexes=projects&page=2&per_page=5')
    assert response.status_code == 200
    
    response_json = response.json()
    assert response_json['page'] == 2
    assert response_json['per_page'] == 5
    
    # Check that pagination is applied to individual indexes
    projects_result = response_json['results']['projects']
    assert projects_result['page'] == 2
    assert projects_result['per_page'] == 5

def test_multi_search_invalid_index(client: TestClient, opensearch_client: OpenSearch):
    '''Test multi-search with invalid index'''
    response = client.get('/api/v1/search?query=test&indexes=invalid_index')
    assert response.status_code == 400
    
    response_json = response.json()
    assert 'detail' in response_json
    assert 'Invalid indexes' in response_json['detail']

def test_multi_search_no_indexes(client: TestClient, opensearch_client: OpenSearch):
    '''Test multi-search with no indexes specified'''
    response = client.get('/api/v1/search?query=test')
    assert response.status_code == 422  # FastAPI validation error

def test_multi_search_mixed_valid_invalid_indexes(client: TestClient, opensearch_client: OpenSearch):
    '''Test multi-search with mix of valid and invalid indexes'''
    response = client.get('/api/v1/search?query=test&indexes=projects&indexes=invalid_index')
    assert response.status_code == 400
    
    response_json = response.json()
    assert 'Invalid indexes' in response_json['detail']

def test_multi_search_sorting(client: TestClient, opensearch_client: OpenSearch):
    '''Test multi-search with sorting'''
    response = client.get('/api/v1/search?query=test&indexes=projects&sort_by=name&sort_order=desc')
    assert response.status_code == 200
    
    response_json = response.json()
    assert 'results' in response_json
    # Sorting should be applied to each index individually

def test_multi_search_per_page_limits(client: TestClient, opensearch_client: OpenSearch):
    '''Test multi-search per_page limits'''
    # Test maximum per_page limit
    response = client.get('/api/v1/search?query=test&indexes=projects&per_page=100')
    assert response.status_code == 200
    
    # Test exceeding maximum per_page limit
    response = client.get('/api/v1/search?query=test&indexes=projects&per_page=101')
    assert response.status_code == 422  # FastAPI validation error

def test_multi_search_computed_fields(client: TestClient, opensearch_client: OpenSearch):
    '''Test computed fields in multi-search response'''
    response = client.get('/api/v1/search?query=test&indexes=projects&indexes=samples')
    assert response.status_code == 200
    
    response_json = response.json()
    
    # Test summary computed field
    assert 'summary' in response_json
    assert isinstance(response_json['summary'], dict)
    assert 'projects' in response_json['summary']
    assert 'samples' in response_json['summary']
    
    # Test success_rate computed field
    assert 'success_rate' in response_json
    assert isinstance(response_json['success_rate'], float)
    assert 0.0 <= response_json['success_rate'] <= 100.0
    
    # Test total_pages computed field for individual results
    for result in response_json['results'].values():
        assert 'total_pages' in result
        assert isinstance(result['total_pages'], int)
        assert result['total_pages'] >= 0

def test_multi_search_error_handling(client: TestClient, opensearch_client: OpenSearch):
    '''Test error handling in multi-search'''
    # This test would require mocking OpenSearch failures
    # For now, we test the basic structure
    response = client.get('/api/v1/search?query=test&indexes=projects')
    assert response.status_code == 200
    
    response_json = response.json()
    assert 'partial_failure' in response_json
    assert isinstance(response_json['partial_failure'], bool)

# Legacy test for backward compatibility during development
def test_search_projects_legacy_compatibility(client: TestClient, opensearch_client: OpenSearch):
    '''Test that the new multi-search can handle single index like the old API'''
    # Add a project to search for
    new_project = {
        "name": "Legacy Test Project",
        "attributes": [
            {"key": "description", "value": "Testing legacy compatibility"},
            {"key": "type", "value": "test"}
        ]
    }

    response = client.post('/api/v1/projects', json=new_project)
    assert response.status_code == 201

    # Search using new multi-index API with single index
    response = client.get('/api/v1/search?query=Legacy&indexes=projects')
    assert response.status_code == 200
    
    response_json = response.json()
    
    # Verify we can extract the same information as the old API
    projects_result = response_json['results']['projects']
    assert projects_result['success'] == True
    assert len(projects_result['items']) == 1
    
    project = projects_result['items'][0]
    assert project['name'] == 'Legacy Test Project'
    assert project['index_name'] == 'projects'
