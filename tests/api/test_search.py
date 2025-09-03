'''
Test /search endpoint
'''

from fastapi.testclient import TestClient
from opensearchpy import OpenSearch
from urllib.parse import urlencode, quote

from core.deps import SessionDep
from tests.fixtures.test_projects import TEST_PROJECTS, basic_projects, SEARCH_TERMS


## New tests

def test_search_projects(client: TestClient, opensearch_client: OpenSearch):
    """
    Project search that returns a ProjectsPublic model
    with sorting and pagination for rendering the table
    on the projects page. 

    This is equivalent to the get projects endpoint, except that
    the searching and pagination is handled by OpenSearch, rather
    than handling pagination from the database.
    """

    # Define the url
    # this can be changed if it replaces the
    # /api/v1/projects endpoint.
    url = '/api/v1/projects/search'

    # Test No projects, this also ensure we are using the test db
    response = client.get(f'{url}', params={'query': 'AI'})
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
    response = client.get(f'{url}', params={'query': 'AI'})
    assert response.status_code == 200
    response_json = response.json()

    # Check the data structure
    assert 'data' in response_json
    assert len(response_json['data']) == 1
    assert response_json['total_items'] == 1
    assert response_json['total_pages'] == 1
    assert response_json['current_page'] == 1
    assert response_json['per_page'] == 20
    assert response_json['has_next'] == False
    assert response_json['has_prev'] == False

    # # Verify project details
    project = response_json['data'][0]  # Changed from 'data' to 'projects'
    assert project['name'] == 'AI Research'


def test_search_projects_paging(client: TestClient, opensearch_client: OpenSearch):
    """
    Test that pagination works on the data returned by the projects search
    endpoint.
    """
    # Populate the database with test projects
    for project in basic_projects:
        response = client.post('/api/v1/projects', json=project)
        assert response.status_code == 201

    # Update with projects search endpoint
    url = '/api/v1/projects/search'
    params = {
        "query": "", # "*" doesn't work in pytest, but "" does
        "page": 1,
        "per_page": 1
    }
    response = client.get(url, params=params)
    assert response.status_code == 200
    response_json = response.json()
    
    ## Should be 3 items on 3 total pages
    assert response_json['data'][0]['name'] == 'Test project 1'
    assert len(response_json['data']) == 1
    assert response_json['total_items'] == 3
    assert response_json['total_pages'] == 3
    assert response_json['current_page'] == 1
    assert response_json['per_page'] == 1
    assert response_json['has_next'] == True
    assert response_json['has_prev'] == False

    # Second page
    params = {
        "query": "", # "*" doesn't work in pytest, but "" does
        "page": 2,
        "per_page": 1
    }
    response = client.get(url, params=params)
    assert response.status_code == 200
    response_json = response.json()
    
    assert response_json['data'][0]['name'] == 'Test project 2'
    assert response_json['has_next'] == True
    assert response_json['has_prev'] == True

    # Third page
    params = {
        "query": "", # "*" doesn't work in pytest, but "" does
        "page": 3,
        "per_page": 1
    }
    response = client.get(url, params=params)
    assert response.status_code == 200
    response_json = response.json()
    
    assert response_json['data'][0]['name'] == 'Test project 3'
    assert response_json['has_next'] == False
    assert response_json['has_prev'] == True

def test_search_projects_sorting(client: TestClient, opensearch_client: OpenSearch):
    """
    Test that sorting works on the data returned by the projects search
    endpoint, even across pagination.
    """
    # Populate the database with test projects
    for project in basic_projects:
        response = client.post('/api/v1/projects', json=project)
        assert response.status_code == 201

    # Update with projects search endpoint
    url = '/api/v1/projects/search'

    ## Sort name ascending
    params = {
        "query": "", # "*" doesn't work in pytest, but "" does
        "page": 1,
        "per_page": 3,
        "sort_by": 'name',
        "sort_order": 'asc'
    }
    response = client.get(url, params=params)
    assert response.status_code == 200
    response_json = response.json()
    assert response_json['data'][0]['name'] == 'Test project 1'

    ## Sort name ascending with pagination
    params = {
        "query": "", # "*" doesn't work in pytest, but "" does
        "page": 1,
        "per_page": 1,
        "sort_by": 'name',
        "sort_order": 'asc'
    }
    response = client.get(url, params=params)
    assert response.status_code == 200
    response_json = response.json()
    assert response_json['data'][0]['name'] == 'Test project 1'

    ## Sort name descending
    params = {
        "query": "", # "*" doesn't work in pytest, but "" does
        "page": 1,
        "per_page": 3,
        "sort_by": 'name',
        "sort_order": 'desc'
    }
    response = client.get(url, params=params)
    assert response.status_code == 200
    response_json = response.json()
    assert response_json['data'][0]['name'] == 'Test project 3'

    ## Sort name descending with pagination
    params = {
        "query": "", # "*" doesn't work in pytest, but "" does
        "page": 1,
        "per_page": 1,
        "sort_by": 'name',
        "sort_order": 'desc'
    }
    response = client.get(url, params=params)
    assert response.status_code == 200
    response_json = response.json()
    assert response_json['data'][0]['name'] == 'Test project 3'


def test_search_runs(client: TestClient, opensearch_client: OpenSearch):
    """
    Run search that returns a SequencingRunsPublic model
    with sorting and pagination for rendering the table
    on the illumin_runs page. 

    This is equivalent to the get runs endpoint, except that
    the searching and pagination is handled by OpenSearch, rather
    than handling pagination from the database.
    """
    # Define the url
    # this can be changed if it replaces the
    # /api/v1/runs endpoint.
    url = '/api/v1/runs/search'

    # Test No runs, this also ensure we are using the test db
    response = client.get(f'{url}', params={'query': 'AI'})
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

    # Add a run to search for
    # update when post endpoint is created
    # new_run = {
    #     "run_date": "2025-08-26",
    #     "machine_id": "MN01165",
    #     "run_number": 78,
    #     "flowcell_id": "A000H5LCGF",
    #     "experiment_name": "Experiment 1",
    #     "s3_run_folder_path": "s3://path/to/data",
    #     "status": "Ready",
    #     "run_time": "",
    #     "barcode": "130719_M00141_0225_000000000-A52TT"
    # }

    # response = client.post('/api/v1/runs', json=new_run)
    # assert response.status_code == 201

    # Now search for the run
    # response = client.get(f'{url}', params={'query': 'AI'})
    # assert response.status_code == 200
    # response_json = response.json()

    # # Check the data structure
    # assert 'data' in response_json
    # assert len(response_json['data']) == 1
    # assert response_json['total_items'] == 1
    # assert response_json['total_pages'] == 1
    # assert response_json['current_page'] == 1
    # assert response_json['per_page'] == 20
    # assert response_json['has_next'] == False
    # assert response_json['has_prev'] == False

    # # Verify run details
    # run = response_json['data'][0]
    # assert run['experiment_name'] == 'Experiment 1'

def test_search_runs_paging(client: TestClient, opensearch_client: OpenSearch):
    """
    Test that pagination works on the data returned by the runs search
    endpoint.
    """
    # TODO: Test once /api/v1/search post is implemented
    pass

def test_search_runs_sorting(client: TestClient, opensearch_client: OpenSearch):
    """
    Test that sorting works on the data returned by the runs search
    endpoint, even across pagination.
    """
    # TODO: Test once /api/v1/search post is implemented
    pass

def test_search(client: TestClient, opensearch_client: OpenSearch):
    """
    Test unified search endpoint for search bar that
    returns a response model for each index in OpenSearch.

    For example, if projects and runs both exist, then the return
    structure should be

    SearchResponse:
        projects: ProjectsPublic
        runs: SequencingRunsPublic
    
    where ProjectsPublic is returned by the get projects endpoint and
    SequencingRunsPublic is returned by the get runs endpoint.

    Each new index should append another prop to this SearchResponse.
    """
    # Populate the database with test projects
    for project in basic_projects:
        response = client.post('/api/v1/projects', json=project)
        assert response.status_code == 201
    
    # Define search url
    url = "/api/v1/search"
    
    params = {
        "query": "", # "*" doesn't work in pytest, but "" does
        "n_results": 5
    }
    response = client.get(url, params=params)
    assert response.status_code == 200
    response_json = response.json()

    # Has projects and runs indicies (even if no data is returned)
    assert 'projects' in response_json
    assert 'runs' in response_json

    # Data is returned (update runs when populated)
    assert response_json['projects']['data']
    assert response_json['runs']['data'] == []
    projects = response_json['projects']
    runs = response_json['runs']

    # Project structure
    assert projects['data'][0]['name'] == 'Test project 1'
    assert len(projects['data']) == 3
    assert projects['total_items'] == 3
    assert projects['total_pages'] == 1
    assert projects['current_page'] == 1
    assert projects['per_page'] == 5
    assert projects['has_next'] == False
    assert projects['has_prev'] == False

    # Run structure
    assert len(runs['data']) == 0
    assert runs['total_items'] == 0
    assert runs['total_pages'] == 0
    assert runs['current_page'] == 1
    assert runs['per_page'] == 5
    assert runs['has_next'] == False
    assert runs['has_prev'] == False
