"""
Test /search endpoint
"""

from fastapi.testclient import TestClient
from opensearchpy import OpenSearch

from tests.fixtures.test_projects import basic_projects


def test_search_projects(client: TestClient):
    """
    Project search that returns a ProjectsPublic model
    with sorting and pagination for rendering the table
    on the projects page.

    This is equivalent to the get projects endpoint, except that
    the searching and pagination is handled by OpenSearch, rather
    than handling pagination from the database.
    """

    url = "/api/v1/projects/search"

    # Test No projects, this also ensure we are using the test db
    response = client.get(f"{url}", params={"query": "AI"})
    assert response.status_code == 200
    assert response.json() == {
        "data": [],
        "total_items": 0,
        "total_pages": 0,
        "current_page": 1,
        "per_page": 20,
        "has_next": False,
        "has_prev": False,
    }

    # Add a project to search for
    new_project = {
        "name": "AI Research",
        "attributes": [
            {"key": "description", "value": "Exploring AI techniques"},
            {"key": "Department", "value": "R&D"},
            {"key": "Priority", "value": "High"},
        ],
    }

    response = client.post("/api/v1/projects", json=new_project)
    assert response.status_code == 201

    # Now search for the project
    response = client.get(f"{url}", params={"query": "AI"})
    assert response.status_code == 200
    response_json = response.json()

    # Check the data structure
    assert "data" in response_json
    assert len(response_json["data"]) == 1
    assert response_json["total_items"] == 1
    assert response_json["total_pages"] == 1
    assert response_json["current_page"] == 1
    assert response_json["per_page"] == 20
    assert response_json["has_next"] is False
    assert response_json["has_prev"] is False

    # Verify project details
    project = response_json["data"][0]
    assert project["name"] == "AI Research"


def test_search_projects_paging(client: TestClient):
    """
    Test that pagination works on the data returned by the projects search
    endpoint.
    """
    # Populate the database with test projects
    for project in basic_projects:
        response = client.post("/api/v1/projects", json=project)
        assert response.status_code == 201

    # Update with projects search endpoint
    url = "/api/v1/projects/search"
    params = {
        "query": "*",
        "page": 1,
        "per_page": 1,
    }
    response = client.get(url, params=params)
    assert response.status_code == 200
    response_json = response.json()

    # Should be 3 items on 3 total pages
    assert response_json["data"][0]["name"] == "Test project 1"
    assert len(response_json["data"]) == 1
    assert response_json["total_items"] == 3
    assert response_json["total_pages"] == 3
    assert response_json["current_page"] == 1
    assert response_json["per_page"] == 1
    assert response_json["has_next"] is True
    assert response_json["has_prev"] is False

    # Second page
    params = {
        "query": "*",
        "page": 2,
        "per_page": 1,
    }
    response = client.get(url, params=params)
    assert response.status_code == 200
    response_json = response.json()

    assert response_json["data"][0]["name"] == "Test project 2"
    assert response_json["has_next"] is True
    assert response_json["has_prev"] is True

    # Third page
    params = {
        "query": "*",
        "page": 3,
        "per_page": 1,
    }
    response = client.get(url, params=params)
    assert response.status_code == 200
    response_json = response.json()

    assert response_json["data"][0]["name"] == "Test project 3"
    assert response_json["has_next"] is False
    assert response_json["has_prev"] is True


def test_search_projects_sorting(client: TestClient):
    """
    Test that sorting works on the data returned by the projects search
    endpoint, even across pagination.
    """
    # Populate the database with test projects
    for project in basic_projects:
        response = client.post("/api/v1/projects", json=project)
        assert response.status_code == 201

    # Update with projects search endpoint
    url = "/api/v1/projects/search"

    # Sort name ascending
    params = {
        "query": "*",
        "page": 1,
        "per_page": 3,
        "sort_by": "name",
        "sort_order": "asc",
    }
    response = client.get(url, params=params)
    assert response.status_code == 200
    response_json = response.json()
    assert response_json["data"][0]["name"] == "Test project 1"

    # Sort name ascending with pagination
    params = {
        "query": "*",
        "page": 1,
        "per_page": 1,
        "sort_by": "name",
        "sort_order": "asc",
    }
    response = client.get(url, params=params)
    assert response.status_code == 200
    response_json = response.json()
    assert response_json["data"][0]["name"] == "Test project 1"

    # Sort name descending
    params = {
        "query": "*",
        "page": 1,
        "per_page": 3,
        "sort_by": "name",
        "sort_order": "desc",
    }
    response = client.get(url, params=params)
    assert response.status_code == 200
    response_json = response.json()
    assert response_json["data"][0]["name"] == "Test project 3"

    # Sort name descending with pagination
    params = {
        "query": "*",
        "page": 1,
        "per_page": 1,
        "sort_by": "name",
        "sort_order": "desc",
    }
    response = client.get(url, params=params)
    assert response.status_code == 200
    response_json = response.json()
    assert response_json["data"][0]["name"] == "Test project 3"


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
        response = client.post("/api/v1/projects", json=project)
        assert response.status_code == 201

    # Define search url
    url = "/api/v1/search"

    params = {"query": "*", "n_results": 5}
    response = client.get(url, params=params)
    assert response.status_code == 200
    response_json = response.json()

    # Has projects and runs indicies (even if no data is returned)
    assert "projects" in response_json
    assert "runs" in response_json

    # Data is returned (update runs when populated)
    assert response_json["projects"]["data"]
    assert response_json["runs"]["data"] == []
    projects = response_json["projects"]
    runs = response_json["runs"]

    # Project structure
    assert projects["data"][0]["name"] == "Test project 1"
    assert len(projects["data"]) == 3
    assert projects["total_items"] == 3
    assert projects["total_pages"] == 1
    assert projects["current_page"] == 1
    assert projects["per_page"] == 5
    assert projects["has_next"] is False
    assert projects["has_prev"] is False

    # Run structure
    assert len(runs["data"]) == 0
    assert runs["total_items"] == 0
    assert runs["total_pages"] == 0
    assert runs["current_page"] == 1
    assert runs["per_page"] == 5
    assert runs["has_next"] is False
    assert runs["has_prev"] is False
