"""Integration tests for file creation API."""

from fastapi.testclient import TestClient


def test_create_file_via_api_with_subdirectory(client: TestClient, test_project):
    """Test file creation via API with subdirectory."""
    response = client.post(
        "/api/v1/files/upload",
        data={
            "filename": "test.txt",
            "entity_type": "project",
            "entity_id": test_project.project_id,
            "relative_path": "raw_data/sample1",
            "description": "Test file in subdirectory",
        },
        files={"content": ("test.txt", b"test content", "text/plain")},
    )

    assert response.status_code == 201
    data = response.json()
    assert "test.txt" in data["uri"]
    assert "raw_data/sample1" in data["uri"]


def test_create_file_via_api_at_root(client: TestClient, test_project):
    """Test file creation via API at entity root."""
    response = client.post(
        "/api/v1/files/upload",
        data={
            "filename": "report.pdf",
            "entity_type": "project",
            "entity_id": test_project.project_id,
            # relative_path not provided - file goes to root
            "description": "Project report",
        },
        files={"content": ("report.pdf", b"%PDF-1.4...", "application/pdf")},
    )

    assert response.status_code == 201
    data = response.json()
    assert "report.pdf" in data["uri"]
    # Should not have extra path components between entity_id and filename
    assert f"{test_project.project_id}/" in data["uri"]


def test_create_file_with_path_traversal(client: TestClient, test_project):
    """Test that path traversal attempts are rejected."""
    response = client.post(
        "/api/v1/files/upload",
        data={
            "filename": "malicious.txt",
            "entity_type": "project",
            "entity_id": test_project.project_id,
            "relative_path": "../../../etc/passwd",
        },
        files={"content": ("malicious.txt", b"attack", "text/plain")},
    )

    assert response.status_code == 400
    assert "Invalid relative_path" in response.json()["detail"]
