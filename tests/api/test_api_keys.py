"""
Tests for API key management and authentication
"""
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session

from api.auth.models import User, APIKey
from core.security import hash_password


@pytest.fixture(name="test_user")
def test_user_fixture(session: Session):
    """Create a verified, active test user in the DB."""
    user = User(
        email="apikey-user@example.com",
        username="apikeyuser",
        hashed_password=hash_password("TestPassword123"),
        full_name="API Key User",
        is_active=True,
        is_verified=True,
        is_superuser=False,
    )
    session.add(user)
    session.commit()
    session.refresh(user)
    return user


@pytest.fixture(name="other_user")
def other_user_fixture(session: Session):
    """Create a second user for isolation tests."""
    user = User(
        email="other-user@example.com",
        username="otheruser",
        hashed_password=hash_password("TestPassword123"),
        full_name="Other User",
        is_active=True,
        is_verified=True,
        is_superuser=False,
    )
    session.add(user)
    session.commit()
    session.refresh(user)
    return user


def _login(client: TestClient, email: str) -> str:
    """Helper: login and return access_token."""
    resp = client.post(
        "/api/v1/auth/login",
        data={"username": email, "password": "TestPassword123"},
    )
    assert resp.status_code == 200
    return resp.json()["access_token"]


class TestAPIKeyCreate:
    """Test API key creation."""

    def test_create_api_key(self, unauthenticated_client: TestClient, test_user):
        token = _login(unauthenticated_client, test_user.email)
        resp = unauthenticated_client.post(
            "/api/v1/auth/api-keys",
            json={"name": "My CI Key"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["name"] == "My CI Key"
        assert data["key"].startswith("ngs360_")
        assert data["key_prefix"] == data["key"][:12]
        assert data["id"] is not None
        assert data["expires_at"] is None

    def test_create_api_key_with_expiry(self, unauthenticated_client: TestClient, test_user):
        token = _login(unauthenticated_client, test_user.email)
        future = (datetime.now(timezone.utc) + timedelta(days=30)).isoformat()
        resp = unauthenticated_client.post(
            "/api/v1/auth/api-keys",
            json={"name": "Expiring Key", "expires_at": future},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 201
        assert resp.json()["expires_at"] is not None

    def test_create_api_key_max_limit(
        self, unauthenticated_client: TestClient, test_user, session: Session
    ):
        """Creating more than 25 active keys returns 400."""
        from api.auth.services import MAX_API_KEYS_PER_USER
        from core.security import generate_api_key

        # Seed 25 keys directly in DB
        for i in range(MAX_API_KEYS_PER_USER):
            _, hashed, prefix = generate_api_key()
            key = APIKey(
                user_id=test_user.id,
                name=f"key-{i}",
                key_prefix=prefix,
                hashed_key=hashed,
                is_active=True,
            )
            session.add(key)
        session.commit()

        token = _login(unauthenticated_client, test_user.email)
        resp = unauthenticated_client.post(
            "/api/v1/auth/api-keys",
            json={"name": "One Too Many"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 400
        assert "25" in resp.json()["detail"]


class TestAPIKeyList:
    """Test listing API keys."""

    def test_list_keys_empty(self, unauthenticated_client: TestClient, test_user):
        token = _login(unauthenticated_client, test_user.email)
        resp = unauthenticated_client.get(
            "/api/v1/auth/api-keys",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 0
        assert data["data"] == []

    def test_list_keys_no_raw_key(self, unauthenticated_client: TestClient, test_user):
        """Listing keys must NOT expose the raw key."""
        token = _login(unauthenticated_client, test_user.email)

        # Create a key
        unauthenticated_client.post(
            "/api/v1/auth/api-keys",
            json={"name": "Listed Key"},
            headers={"Authorization": f"Bearer {token}"},
        )

        resp = unauthenticated_client.get(
            "/api/v1/auth/api-keys",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 1
        item = data["data"][0]
        assert "key" not in item
        assert "hashed_key" not in item
        assert item["key_prefix"].startswith("ngs360_")


class TestAPIKeyAuth:
    """Test authenticating with an API key."""

    def test_auth_with_api_key(self, unauthenticated_client: TestClient, test_user):
        """Using a raw API key as Bearer token on /auth/me returns 200."""
        jwt_token = _login(unauthenticated_client, test_user.email)
        create_resp = unauthenticated_client.post(
            "/api/v1/auth/api-keys",
            json={"name": "Auth Test Key"},
            headers={"Authorization": f"Bearer {jwt_token}"},
        )
        raw_key = create_resp.json()["key"]

        resp = unauthenticated_client.get(
            "/api/v1/auth/me",
            headers={"Authorization": f"Bearer {raw_key}"},
        )
        assert resp.status_code == 200
        assert resp.json()["email"] == test_user.email

    def test_last_used_at_updated(
        self, unauthenticated_client: TestClient, test_user, session: Session
    ):
        """last_used_at is updated after authenticating with an API key."""
        jwt_token = _login(unauthenticated_client, test_user.email)
        create_resp = unauthenticated_client.post(
            "/api/v1/auth/api-keys",
            json={"name": "Tracked Key"},
            headers={"Authorization": f"Bearer {jwt_token}"},
        )
        key_id = create_resp.json()["id"]
        raw_key = create_resp.json()["key"]

        # Use the key
        unauthenticated_client.get(
            "/api/v1/auth/me",
            headers={"Authorization": f"Bearer {raw_key}"},
        )

        # Check last_used_at was set
        api_key = session.get(APIKey, uuid.UUID(key_id))
        assert api_key.last_used_at is not None

    def test_revoked_key_returns_401(self, unauthenticated_client: TestClient, test_user):
        """Revoking a key then using it for auth returns 401."""
        jwt_token = _login(unauthenticated_client, test_user.email)

        create_resp = unauthenticated_client.post(
            "/api/v1/auth/api-keys",
            json={"name": "Revoke Me"},
            headers={"Authorization": f"Bearer {jwt_token}"},
        )
        key_id = create_resp.json()["id"]
        raw_key = create_resp.json()["key"]

        # Revoke
        unauthenticated_client.post(
            f"/api/v1/auth/api-keys/{key_id}/revoke",
            headers={"Authorization": f"Bearer {jwt_token}"},
        )

        # Try to auth with revoked key
        resp = unauthenticated_client.get(
            "/api/v1/auth/me",
            headers={"Authorization": f"Bearer {raw_key}"},
        )
        assert resp.status_code == 401

    def test_expired_key_returns_401(
        self, unauthenticated_client: TestClient, test_user, session: Session
    ):
        """An expired API key returns 401."""
        from core.security import generate_api_key

        raw_key, hashed, prefix = generate_api_key()
        expired_key = APIKey(
            user_id=test_user.id,
            name="Expired Key",
            key_prefix=prefix,
            hashed_key=hashed,
            expires_at=datetime.now(timezone.utc) - timedelta(hours=1),
            is_active=True,
        )
        session.add(expired_key)
        session.commit()

        resp = unauthenticated_client.get(
            "/api/v1/auth/me",
            headers={"Authorization": f"Bearer {raw_key}"},
        )
        assert resp.status_code == 401


class TestAPIKeyRevoke:
    """Test revoking API keys."""

    def test_revoke_key(self, unauthenticated_client: TestClient, test_user):
        jwt_token = _login(unauthenticated_client, test_user.email)
        create_resp = unauthenticated_client.post(
            "/api/v1/auth/api-keys",
            json={"name": "To Revoke"},
            headers={"Authorization": f"Bearer {jwt_token}"},
        )
        key_id = create_resp.json()["id"]

        resp = unauthenticated_client.post(
            f"/api/v1/auth/api-keys/{key_id}/revoke",
            headers={"Authorization": f"Bearer {jwt_token}"},
        )
        assert resp.status_code == 200
        assert resp.json()["is_active"] is False
        assert resp.json()["revoked_at"] is not None


class TestAPIKeyDelete:
    """Test deleting API keys."""

    def test_delete_key(self, unauthenticated_client: TestClient, test_user):
        jwt_token = _login(unauthenticated_client, test_user.email)

        create_resp = unauthenticated_client.post(
            "/api/v1/auth/api-keys",
            json={"name": "To Delete"},
            headers={"Authorization": f"Bearer {jwt_token}"},
        )
        key_id = create_resp.json()["id"]

        resp = unauthenticated_client.delete(
            f"/api/v1/auth/api-keys/{key_id}",
            headers={"Authorization": f"Bearer {jwt_token}"},
        )
        assert resp.status_code == 204

        # Confirm it's gone from list
        list_resp = unauthenticated_client.get(
            "/api/v1/auth/api-keys",
            headers={"Authorization": f"Bearer {jwt_token}"},
        )
        assert list_resp.json()["count"] == 0


class TestAPIKeyUserIsolation:
    """Test that users can't access each other's keys."""

    def test_cannot_revoke_other_users_key(
        self, unauthenticated_client: TestClient, test_user, other_user
    ):
        # User A creates a key
        token_a = _login(unauthenticated_client, test_user.email)
        create_resp = unauthenticated_client.post(
            "/api/v1/auth/api-keys",
            json={"name": "User A's Key"},
            headers={"Authorization": f"Bearer {token_a}"},
        )
        key_id = create_resp.json()["id"]

        # User B tries to revoke it
        token_b = _login(unauthenticated_client, other_user.email)
        resp = unauthenticated_client.post(
            f"/api/v1/auth/api-keys/{key_id}/revoke",
            headers={"Authorization": f"Bearer {token_b}"},
        )
        assert resp.status_code == 404

    def test_cannot_delete_other_users_key(
        self, unauthenticated_client: TestClient, test_user, other_user
    ):
        token_a = _login(unauthenticated_client, test_user.email)
        create_resp = unauthenticated_client.post(
            "/api/v1/auth/api-keys",
            json={"name": "User A's Key"},
            headers={"Authorization": f"Bearer {token_a}"},
        )
        key_id = create_resp.json()["id"]

        token_b = _login(unauthenticated_client, other_user.email)
        resp = unauthenticated_client.delete(
            f"/api/v1/auth/api-keys/{key_id}",
            headers={"Authorization": f"Bearer {token_b}"},
        )
        assert resp.status_code == 404
