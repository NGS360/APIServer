"""Tests for Platform CRUD endpoints."""

from fastapi.testclient import TestClient


# ---------------------------------------------------------------------------
# POST /platforms
# ---------------------------------------------------------------------------

def test_create_platform(client: TestClient):
    """Create a new platform."""
    body = {"name": "Arvados"}
    resp = client.post("/api/v1/platforms", json=body)
    assert resp.status_code == 201
    data = resp.json()
    assert data["name"] == "Arvados"
    assert "id" in data


def test_create_platform_duplicate(client: TestClient):
    """Duplicate platform name returns 409."""
    body = {"name": "Arvados"}
    resp1 = client.post("/api/v1/platforms", json=body)
    assert resp1.status_code == 201

    resp2 = client.post("/api/v1/platforms", json=body)
    assert resp2.status_code == 409


# ---------------------------------------------------------------------------
# GET /platforms
# ---------------------------------------------------------------------------

def test_get_platforms_empty(client: TestClient):
    """List platforms when none exist returns empty list."""
    resp = client.get("/api/v1/platforms")
    assert resp.status_code == 200
    assert resp.json() == []


def test_get_platforms(client: TestClient):
    """List platforms after creating two."""
    client.post("/api/v1/platforms", json={"name": "Arvados"})
    client.post("/api/v1/platforms", json={"name": "SevenBridges"})

    resp = client.get("/api/v1/platforms")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 2
    names = {p["name"] for p in data}
    assert names == {"Arvados", "SevenBridges"}


# ---------------------------------------------------------------------------
# GET /platforms/{name}
# ---------------------------------------------------------------------------

def test_get_platform_by_name(client: TestClient):
    """Fetch a single platform by name."""
    client.post("/api/v1/platforms", json={"name": "Arvados"})

    resp = client.get("/api/v1/platforms/Arvados")
    assert resp.status_code == 200
    assert resp.json()["name"] == "Arvados"


def test_get_platform_not_found(client: TestClient):
    """Fetching a non-existent platform returns 404."""
    resp = client.get("/api/v1/platforms/Nonexistent")
    assert resp.status_code == 404
