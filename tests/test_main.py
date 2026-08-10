from fastapi.testclient import TestClient

from main import app

client = TestClient(app)


def test_read_main(client: TestClient):
    response = client.get("/")
    assert response.status_code == 200
    assert response.json() == {
        "message": "Welcome to the NGS360 API! Visit /docs for API documentation."
    }


def test_health_check(client: TestClient):
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "message": "NGS360 API is running."}


def test_health_check_uses_the_injected_session(client: TestClient):
    """
    The probe must go through get_db, not the module-level engine.

    That engine is built at import time from whatever .env names, so a probe
    opening its own session reached a *deployed* database from the test suite --
    which is both wrong and why this test used to fail only when DNS happened
    not to resolve. Overriding the dependency with a session that refuses to
    execute proves the endpoint honours the override, and that an unreachable
    database still degrades to a clean 503 rather than a 500.
    """
    from core.deps import get_db

    class UnreachableSession:
        def execute(self, *args, **kwargs):
            raise OSError("database is unreachable")

    previous = app.dependency_overrides.get(get_db)
    app.dependency_overrides[get_db] = lambda: UnreachableSession()
    try:
        response = client.get("/api/health")
    finally:
        if previous is None:
            del app.dependency_overrides[get_db]
        else:
            app.dependency_overrides[get_db] = previous

    assert response.status_code == 503
    assert response.json()["status"] == "error"


def test_validation_error_with_bytes_body_returns_422(client: TestClient):
    """
    Regression test: when a request sends a JSON body without the proper
    Content-Type header, FastAPI receives raw bytes and raises a
    RequestValidationError. The custom validation_exception_handler must
    return a proper 422 response (not crash with a TypeError due to
    bytes not being JSON-serializable).
    """
    body = b'{ "name": "A workflow", "attributes": [] }'
    response = client.post(
        "/api/v1/workflows",
        content=body,
        headers={"Content-Type": "text/plain"},
    )

    # Must get a well-formed 422 response, NOT a 500 server error
    assert response.status_code == 422
    data = response.json()
    assert "detail" in data
    assert "errors" in data

    # Verify the "received" field is a string (not raw bytes)
    for error in data["errors"]:
        if "received" in error:
            assert isinstance(error["received"], str)
