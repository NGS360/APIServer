'''
Test /search endpoint
'''

from fastapi.testclient import TestClient
from opensearchpy import OpenSearch

from tests.fixtures.test_projects import TEST_PROJECTS, SEARCH_TERMS

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
    assert response_json == {"total_items":0,"total_pages":0,"current_page":1,"per_page":0,"has_next":False,"has_prev":False, "data": []}


def test_search_paging(client: TestClient, opensearch_client: OpenSearch):
    ''' Test that paging in OpenSearch searches work correctly '''
    # Populate the database with multiple projects
    for project in TEST_PROJECTS:
        response = client.post("/api/v1/projects", json=project)
        assert response.status_code == 201

    # First, let's test with a broader search to get multiple results
    # Use a search term that should match multiple projects
    search_term = 'Project'  # This should match projects that have "Project" in their name
    
    # Add some additional projects to ensure we have enough for pagination testing
    additional_projects = [
        {
            "name": "Alpha Project Test",
            "attributes": [
                {"key": "description", "value": "Test project for pagination"},
                {"key": "Department", "value": "Testing"}
            ]
        },
        {
            "name": "Beta Project Test",
            "attributes": [
                {"key": "description", "value": "Another test project for pagination"},
                {"key": "Department", "value": "Testing"}
            ]
        },
        {
            "name": "Gamma Project Test",
            "attributes": [
                {"key": "description", "value": "Third test project for pagination"},
                {"key": "Department", "value": "Testing"}
            ]
        }
    ]
    
    for project in additional_projects:
        response = client.post("/api/v1/projects", json=project)
        assert response.status_code == 201
    
    # Test first page with 3 items per page
    response = client.get(f'/api/v1/search?query={search_term}&index=projects&page=1&per_page=3&sort_by=name&sort_order=asc')
    assert response.status_code == 200
    page1_data = response.json()
    
    # We should have at least 3 projects with "Project" in the name
    assert len(page1_data['projects']) >= 1  # At least 1 result
    total_items = page1_data['total_items']
    assert total_items >= 3  # Should have at least 3 projects with "Project" in name
    
    # Calculate expected pages
    expected_pages = (total_items + 2) // 3  # Ceiling division for 3 per page
    assert page1_data['total_pages'] == expected_pages
    assert page1_data['current_page'] == 1
    assert page1_data['per_page'] == 3
    assert page1_data['has_prev'] == False
    
    # Verify the projects are sorted by name (ascending)
    project_names_page1 = [project['name'] for project in page1_data['projects']]
    assert project_names_page1 == sorted(project_names_page1)
    
    # Test second page if there are enough results
    if total_items > 3:
        response = client.get(f'/api/v1/search?query={search_term}&index=projects&page=2&per_page=3&sort_by=name&sort_order=asc')
        assert response.status_code == 200
        page2_data = response.json()
        
        # Check pagination metadata
        assert page2_data['total_items'] == total_items
        assert page2_data['total_pages'] == expected_pages
        assert page2_data['current_page'] == 2
        assert page2_data['per_page'] == 3
        assert page2_data['has_prev'] == True
        
        # Verify the projects are sorted by name (ascending)
        project_names_page2 = [project['name'] for project in page2_data['projects']]
        assert project_names_page2 == sorted(project_names_page2)
        
        # Verify no overlap between pages
        all_page1_names = set(project_names_page1)
        all_page2_names = set(project_names_page2)
        assert len(all_page1_names.intersection(all_page2_names)) == 0



def test_search_sorting(client: TestClient, opensearch_client: OpenSearch):
    ''' Test that sorting functionality works correctly '''
    # Add multiple projects with different names for sorting
    projects = [
        {
            "name": "Alpha Project",
            "attributes": [
                {"key": "description", "value": "First project alphabetically"},
                {"key": "Department", "value": "R&D"}
            ]
        },
        {
            "name": "Zeta Project", 
            "attributes": [
                {"key": "description", "value": "Last project alphabetically"},
                {"key": "Department", "value": "R&D"}
            ]
        },
        {
            "name": "Beta Project",
            "attributes": [
                {"key": "description", "value": "Second project alphabetically"},
                {"key": "Department", "value": "R&D"}
            ]
        }
    ]

    # Add all projects
    for project in projects:
        response = client.post('/api/v1/projects', json=project)
        assert response.status_code == 201

    # Test ascending sort
    response = client.get('/api/v1/search?query=Project&index=projects&sort_by=name&sort_order=asc')
    assert response.status_code == 200
    asc_data = response.json()
    
    assert len(asc_data['projects']) == 3
    assert asc_data['projects'][0]['name'] == 'Alpha Project'
    assert asc_data['projects'][1]['name'] == 'Beta Project'
    assert asc_data['projects'][2]['name'] == 'Zeta Project'

    # Test descending sort
    response = client.get('/api/v1/search?query=Project&index=projects&sort_by=name&sort_order=desc')
    assert response.status_code == 200
    desc_data = response.json()
    
    assert len(desc_data['projects']) == 3
    assert desc_data['projects'][0]['name'] == 'Zeta Project'
    assert desc_data['projects'][1]['name'] == 'Beta Project'
    assert desc_data['projects'][2]['name'] == 'Alpha Project'

    # Test sort_by without sort_order (should default to asc)
    response = client.get('/api/v1/search?query=Project&index=projects&sort_by=name')
    assert response.status_code == 200
    default_data = response.json()
    
    assert len(default_data['projects']) == 3
    assert default_data['projects'][0]['name'] == 'Alpha Project'
    assert default_data['projects'][1]['name'] == 'Beta Project'
    assert default_data['projects'][2]['name'] == 'Zeta Project'
