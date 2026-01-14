"""Integration tests for file creation API."""

from fastapi.testclient import TestClient


def test_create_file_via_api_with_subdirectory(client: TestClient, test_project):
    """Test file creation via API with subdirectory."""
    response = client.post(
        "/api/v1/files",
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
    assert data["filename"] == "test.txt"
    assert data["relative_path"] == "raw_data/sample1"
    assert data["entity_id"] == test_project.project_id


def test_create_file_via_api_at_root(client: TestClient, test_project):
    """Test file creation via API at entity root."""
    response = client.post(
        "/api/v1/files",
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
    assert data["filename"] == "report.pdf"
    assert data["relative_path"] is None


def test_create_file_with_path_traversal(client: TestClient, test_project):
    """Test that path traversal attempts are rejected."""
    response = client.post(
        "/api/v1/files",
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
