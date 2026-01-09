""" Test cases for settings-related API endpoints """
from fastapi.testclient import TestClient
from sqlmodel import Session

from api.settings.models import Setting


def test_get_setting_by_key(client: TestClient, session: Session):
    """Test retrieving a specific setting by key"""
    # Create a test setting
    setting = Setting(
        key="TEST_SETTING",
        value="test_value",
        name="Test Setting",
        description="A test setting",
        tags=[{"key": "category", "value": "test"}]
    )
    session.add(setting)
    session.commit()

    # Retrieve the setting by key
    response = client.get("/api/v1/settings/TEST_SETTING")
    assert response.status_code == 200
    data = response.json()

    assert data["key"] == "TEST_SETTING"
    assert data["value"] == "test_value"
    assert data["name"] == "Test Setting"
    assert data["description"] == "A test setting"
    assert len(data["tags"]) == 1
    assert data["tags"][0]["key"] == "category"
    assert data["tags"][0]["value"] == "test"


def test_get_setting_not_found(client: TestClient):
    """Test retrieving a non-existent setting returns 404"""
    response = client.get("/api/v1/settings/NONEXISTENT_KEY")
    assert response.status_code == 404
    assert "not found" in response.json()["detail"].lower()


def test_update_setting_value(client: TestClient, session: Session):
    """Test updating a setting's value"""
    # Create a test setting
    setting = Setting(
        key="UPDATE_TEST",
        value="original_value",
        name="Update Test",
        description="Test updating values",
        tags=[{"key": "category", "value": "test"}]
    )
    session.add(setting)
    session.commit()

    # Update the setting's value
    update_data = {"value": "updated_value"}
    response = client.put("/api/v1/settings/UPDATE_TEST", json=update_data)
    assert response.status_code == 200
    data = response.json()

    assert data["key"] == "UPDATE_TEST"
    assert data["value"] == "updated_value"
    assert data["name"] == "Update Test"  # Should remain unchanged


def test_update_setting_multiple_fields(client: TestClient, session: Session):
    """Test updating multiple fields of a setting"""
    # Create a test setting
    setting = Setting(
        key="MULTI_UPDATE_TEST",
        value="original_value",
        name="Original Name",
        description="Original description",
        tags=[{"key": "category", "value": "original"}]
    )
    session.add(setting)
    session.commit()

    # Update multiple fields
    update_data = {
        "value": "new_value",
        "name": "New Name",
        "description": "New description",
        "tags": [
            {"key": "category", "value": "updated"},
            {"key": "type", "value": "test"}
        ]
    }
    response = client.put("/api/v1/settings/MULTI_UPDATE_TEST", json=update_data)
    assert response.status_code == 200
    data = response.json()

    assert data["key"] == "MULTI_UPDATE_TEST"  # Key should not change
    assert data["value"] == "new_value"
    assert data["name"] == "New Name"
    assert data["description"] == "New description"
    assert len(data["tags"]) == 2
    assert data["tags"][0]["key"] == "category"
    assert data["tags"][0]["value"] == "updated"


def test_update_setting_not_found(client: TestClient):
    """Test updating a non-existent setting returns 404"""
    update_data = {"value": "some_value"}
    response = client.put("/api/v1/settings/NONEXISTENT_KEY", json=update_data)
    assert response.status_code == 404
    assert "not found" in response.json()["detail"].lower()


def test_get_settings_by_tag(client: TestClient, session: Session):
    """Test retrieving settings filtered by tag"""
    # Create multiple test settings with different tags
    settings = [
        Setting(
            key="STORAGE_SETTING_1",
            value="s3://bucket1",
            name="Storage Setting 1",
            tags=[
                {"key": "category", "value": "storage"},
                {"key": "type", "value": "aws-s3"}
            ]
        ),
        Setting(
            key="STORAGE_SETTING_2",
            value="s3://bucket2",
            name="Storage Setting 2",
            tags=[
                {"key": "category", "value": "storage"},
                {"key": "type", "value": "aws-s3"}
            ]
        ),
        Setting(
            key="AUTH_SETTING",
            value="auth_value",
            name="Auth Setting",
            tags=[
                {"key": "category", "value": "authentication"},
                {"key": "type", "value": "credential"}
            ]
        ),
    ]
    for setting in settings:
        session.add(setting)
    session.commit()

    # Retrieve settings by tag
    response = client.get("/api/v1/settings?tag_key=category&tag_value=storage")
    assert response.status_code == 200
    data = response.json()

    assert isinstance(data, list)
    assert len(data) == 2  # Should return 2 storage settings
    assert all(setting["key"].startswith("STORAGE_SETTING") for setting in data)

    # Test with different tag
    response = client.get("/api/v1/settings?tag_key=category&tag_value=authentication")
    assert response.status_code == 200
    data = response.json()

    assert isinstance(data, list)
    assert len(data) == 1
    assert data[0]["key"] == "AUTH_SETTING"


def test_get_settings_by_tag_no_matches(client: TestClient, session: Session):
    """Test retrieving settings by tag with no matches returns empty list"""
    # Create a test setting
    setting = Setting(
        key="SOME_SETTING",
        value="value",
        name="Some Setting",
        tags=[{"key": "category", "value": "test"}]
    )
    session.add(setting)
    session.commit()

    # Query with non-matching tag
    response = client.get("/api/v1/settings?tag_key=category&tag_value=nonexistent")
    assert response.status_code == 200
    data = response.json()

    assert isinstance(data, list)
    assert len(data) == 0


def test_update_setting_partial(client: TestClient, session: Session):
    """Test partial update of a setting (only updating some fields)"""
    # Create a test setting
    setting = Setting(
        key="PARTIAL_UPDATE",
        value="original_value",
        name="Original Name",
        description="Original description",
        tags=[{"key": "category", "value": "test"}]
    )
    session.add(setting)
    session.commit()

    # Update only the value
    update_data = {"value": "new_value"}
    response = client.put("/api/v1/settings/PARTIAL_UPDATE", json=update_data)
    assert response.status_code == 200
    data = response.json()

    # Only value should change, others remain the same
    assert data["value"] == "new_value"
    assert data["name"] == "Original Name"
    assert data["description"] == "Original description"
    assert data["tags"][0]["key"] == "category"
    assert data["tags"][0]["value"] == "test"
