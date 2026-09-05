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

    def test_delete_key_stops_the_credential(
        self, unauthenticated_client: TestClient, test_user
    ):
        """DELETE must still make the key unusable -- that is the whole point."""
        jwt_token = _login(unauthenticated_client, test_user.email)

        create_resp = unauthenticated_client.post(
            "/api/v1/auth/api-keys",
            json={"name": "To Delete"},
            headers={"Authorization": f"Bearer {jwt_token}"},
        )
        key_id = create_resp.json()["id"]
        raw_key = create_resp.json()["key"]

        resp = unauthenticated_client.delete(
            f"/api/v1/auth/api-keys/{key_id}",
            headers={"Authorization": f"Bearer {jwt_token}"},
        )
        assert resp.status_code == 204

        auth = unauthenticated_client.get(
            "/api/v1/auth/me", headers={"Authorization": f"Bearer {raw_key}"}
        )
        assert auth.status_code == 401

    def test_delete_key_keeps_the_record(
        self, unauthenticated_client: TestClient, test_user
    ):
        """
        DELETE retires rather than destroys.

        Hard-deleting the row took the credential *and* every trace it existed
        -- name, owner, creation date, last use, and the fact of retirement --
        which makes "was that key ever active, and when was it turned off?"
        unanswerable. It came up for real: a key hard-deleted during a superuser
        cleanup left no record, while keys revoked in the same hour stayed fully
        accountable.
        """
        jwt_token = _login(unauthenticated_client, test_user.email)

        create_resp = unauthenticated_client.post(
            "/api/v1/auth/api-keys",
            json={"name": "To Delete"},
            headers={"Authorization": f"Bearer {jwt_token}"},
        )
        key_id = create_resp.json()["id"]

        unauthenticated_client.delete(
            f"/api/v1/auth/api-keys/{key_id}",
            headers={"Authorization": f"Bearer {jwt_token}"},
        )

        list_resp = unauthenticated_client.get(
            "/api/v1/auth/api-keys",
            headers={"Authorization": f"Bearer {jwt_token}"},
        )
        assert list_resp.json()["count"] == 1
        record = list_resp.json()["data"][0]
        assert record["id"] == key_id
        assert record["name"] == "To Delete"
        assert record["is_active"] is False
        assert record["revoked_at"] is not None

    def test_delete_and_revoke_are_equivalent(
        self, unauthenticated_client: TestClient, test_user
    ):
        """Two endpoints, one behaviour -- so neither is the unaudited path."""
        jwt_token = _login(unauthenticated_client, test_user.email)
        headers = {"Authorization": f"Bearer {jwt_token}"}

        ids = []
        for name in ("via-delete", "via-revoke"):
            resp = unauthenticated_client.post(
                "/api/v1/auth/api-keys", json={"name": name}, headers=headers
            )
            ids.append(resp.json()["id"])

        unauthenticated_client.delete(
            f"/api/v1/auth/api-keys/{ids[0]}", headers=headers
        )
        unauthenticated_client.post(
            f"/api/v1/auth/api-keys/{ids[1]}/revoke", headers=headers
        )

        listed = unauthenticated_client.get(
            "/api/v1/auth/api-keys", headers=headers
        ).json()["data"]
        by_id = {k["id"]: k for k in listed}
        for key_id in ids:
            assert by_id[key_id]["is_active"] is False
            assert by_id[key_id]["revoked_at"] is not None

    def test_retiring_twice_preserves_the_original_timestamp(
        self, unauthenticated_client: TestClient, test_user
    ):
        """
        Idempotent, and the timestamp is not refreshed. The auditable fact is
        when the credential stopped working, not when someone last asked.
        """
        jwt_token = _login(unauthenticated_client, test_user.email)
        headers = {"Authorization": f"Bearer {jwt_token}"}

        key_id = unauthenticated_client.post(
            "/api/v1/auth/api-keys", json={"name": "Twice"}, headers=headers
        ).json()["id"]

        first = unauthenticated_client.post(
            f"/api/v1/auth/api-keys/{key_id}/revoke", headers=headers
        )
        assert first.status_code == 200
        original = first.json()["revoked_at"]

        again = unauthenticated_client.delete(
            f"/api/v1/auth/api-keys/{key_id}", headers=headers
        )
        assert again.status_code == 204

        listed = unauthenticated_client.get(
            "/api/v1/auth/api-keys", headers=headers
        ).json()["data"]
        assert listed[0]["revoked_at"] == original

    def test_a_retired_key_does_not_consume_quota(
        self, unauthenticated_client: TestClient, test_user
    ):
        """
        Keys now accumulate instead of vanishing, so the cap must count only
        active ones -- otherwise create/delete cycles would slowly lock a user
        out of making keys at all.
        """
        from api.auth.services import MAX_API_KEYS_PER_USER

        jwt_token = _login(unauthenticated_client, test_user.email)
        headers = {"Authorization": f"Bearer {jwt_token}"}

        for i in range(MAX_API_KEYS_PER_USER):
            resp = unauthenticated_client.post(
                "/api/v1/auth/api-keys", json={"name": f"key-{i}"},
                headers=headers,
            )
            assert resp.status_code == 201, resp.text
            if i == 0:
                first_id = resp.json()["id"]

        at_cap = unauthenticated_client.post(
            "/api/v1/auth/api-keys", json={"name": "over"}, headers=headers
        )
        assert at_cap.status_code == 400

        unauthenticated_client.delete(
            f"/api/v1/auth/api-keys/{first_id}", headers=headers
        )

        after = unauthenticated_client.post(
            "/api/v1/auth/api-keys", json={"name": "room-again"},
            headers=headers,
        )
        assert after.status_code == 201, after.text


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
