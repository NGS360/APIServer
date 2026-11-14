"""/auth/me must serialise an account that has no email (for example one created by an OAuth provider
that does not release the email claim)."""
from datetime import datetime, timezone

from fastapi.testclient import TestClient

from main import app


def test_user_public_accepts_a_missing_email():
    from api.auth.models import UserPublic

    info = UserPublic(
        email=None, username="no-email-user", full_name=None,
        is_active=True, is_verified=True, is_superuser=False,
        created_at=datetime.now(timezone.utc), last_login=None,
    )
    assert info.email is None


def test_me_endpoint_for_a_user_without_email(session):
    from api.auth.deps import get_current_user
    from api.auth.models import User
    from core.deps import get_db

    user = User(username="no-email-user", email=None, is_active=True, is_verified=True)
    session.add(user)
    session.commit()
    session.refresh(user)
    app.dependency_overrides[get_db] = lambda: session
    app.dependency_overrides[get_current_user] = lambda: user
    try:
        response = TestClient(app).get("/api/v1/auth/me")
    finally:
        app.dependency_overrides.pop(get_db, None)
        app.dependency_overrides.pop(get_current_user, None)
    assert response.status_code == 200, response.text
    assert response.json()["email"] is None
    assert response.json()["username"] == "no-email-user"
