""" Test cases for request-context middleware and structured logging """
import json
import logging
import uuid

from fastapi.testclient import TestClient

from core.config import get_settings
from core.logger import JsonFormatter
from core.middleware import REQUEST_ID_HEADER, _client_ip, _resolve_principal
from core.security import create_access_token


class _FakeRequest:
    """Minimal stand-in for starlette Request: middleware helpers only read
    .headers, .client and .scope."""

    class _Client:
        def __init__(self, host):
            self.host = host

    def __init__(self, headers=None, client_host=None, route_path=None):
        self.headers = headers or {}
        self.client = self._Client(client_host) if client_host else None
        self.scope = {}
        if route_path is not None:
            self.scope["route"] = type("R", (), {"path": route_path})()


class TestRequestId:
    """Every response carries a request id, echoing the caller's if supplied"""

    def test_request_id_is_added_to_response(self, client: TestClient):
        response = client.get("/api/v1/settings?tag_key=x&tag_value=y")
        assert REQUEST_ID_HEADER in response.headers
        # Generated ids are UUIDs
        uuid.UUID(response.headers[REQUEST_ID_HEADER])

    def test_caller_supplied_request_id_is_echoed(self, client: TestClient):
        supplied = "my-correlation-id-123"
        response = client.get(
            "/api/v1/settings?tag_key=x&tag_value=y",
            headers={REQUEST_ID_HEADER: supplied},
        )
        assert response.headers[REQUEST_ID_HEADER] == supplied

    def test_request_id_present_on_error_responses(self, client: TestClient):
        response = client.get("/api/v1/settings/NO_SUCH_KEY")
        assert response.status_code == 404
        assert REQUEST_ID_HEADER in response.headers


class TestPrincipalResolution:
    """Identity comes from the credential alone, with no database access"""

    def test_no_authorization_header(self):
        result = _resolve_principal(_FakeRequest())
        assert result == {"principal": None, "auth_method": "none", "auth_valid": None}

    def test_non_bearer_scheme_ignored(self):
        result = _resolve_principal(_FakeRequest({"authorization": "Basic abc123"}))
        assert result["auth_method"] == "none"
        assert result["principal"] is None

    def test_valid_jwt_yields_subject(self):
        subject = str(uuid.uuid4())
        token = create_access_token({"sub": subject})
        result = _resolve_principal(
            _FakeRequest({"authorization": f"Bearer {token}"})
        )
        assert result == {
            "principal": subject,
            "auth_method": "jwt",
            "auth_valid": True,
        }

    def test_malformed_jwt_records_the_attempt(self):
        result = _resolve_principal(
            _FakeRequest({"authorization": "Bearer not-a-real-token"})
        )
        # The attempt is recorded, but no principal is claimed.
        assert result == {
            "principal": None,
            "auth_method": "jwt",
            "auth_valid": False,
        }

    def test_api_key_logs_only_its_prefix(self):
        secret = "ngs360_abcdefghijklmnopqrstuvwxyz0123456789"
        result = _resolve_principal(
            _FakeRequest({"authorization": f"Bearer {secret}"})
        )
        assert result["auth_method"] == "api_key"
        # The live credential must never reach the logs.
        assert secret not in result["principal"]
        assert result["principal"] == "ngs360_abcdefgh..."
        assert "ijklmnop" not in result["principal"]

    def test_api_key_validity_is_not_asserted(self):
        """Validating a key needs a DB lookup, which this layer avoids."""
        result = _resolve_principal(
            _FakeRequest({"authorization": "Bearer ngs360_short"})
        )
        assert result["auth_valid"] is None


class TestClientIp:
    """Behind nginx and an ALB, the caller is the left-most forwarded entry"""

    def test_prefers_leftmost_forwarded_for(self):
        request = _FakeRequest(
            {"x-forwarded-for": "203.0.113.7, 10.0.0.1, 10.0.0.2"},
            client_host="10.0.0.2",
        )
        assert _client_ip(request) == "203.0.113.7"

    def test_falls_back_to_socket_peer(self):
        assert _client_ip(_FakeRequest(client_host="192.0.2.5")) == "192.0.2.5"

    def test_returns_none_when_unknown(self):
        assert _client_ip(_FakeRequest()) is None


class TestJsonFormatter:
    """Log lines are single-line JSON with structured fields merged in"""

    def _record(self, **extra):
        record = logging.LogRecord(
            name="test", level=logging.INFO, pathname=__file__, lineno=1,
            msg="hello %s", args=("world",), exc_info=None,
        )
        for key, value in extra.items():
            setattr(record, key, value)
        return record

    def test_emits_single_line_json(self):
        output = JsonFormatter(environment="dev").format(self._record())
        assert "\n" not in output
        parsed = json.loads(output)
        assert parsed["message"] == "hello world"
        assert parsed["level"] == "INFO"
        assert parsed["environment"] == "dev"
        assert parsed["timestamp"].endswith("+00:00")

    def test_extra_fields_are_merged(self):
        output = JsonFormatter(environment="prod").format(
            self._record(event="http.request", status=403, route_name="/api/v1/x")
        )
        parsed = json.loads(output)
        assert parsed["event"] == "http.request"
        assert parsed["status"] == 403
        assert parsed["route_name"] == "/api/v1/x"

    def test_standard_attrs_are_not_duplicated(self):
        parsed = json.loads(JsonFormatter(environment="dev").format(self._record()))
        for noisy in ("msg", "args", "levelno", "pathname", "relativeCreated"):
            assert noisy not in parsed

    def test_unserialisable_values_do_not_raise(self):
        parsed = json.loads(
            JsonFormatter(environment="dev").format(self._record(obj=object()))
        )
        assert isinstance(parsed["obj"], str)


class TestAccessLogging:
    """One structured line per request, with the route template not the path"""

    def test_logs_route_template_not_concrete_path(self, client: TestClient, caplog):
        with caplog.at_level(logging.INFO, logger="core.middleware"):
            client.get("/api/v1/settings/SOME_KEY")
        entries = [r for r in caplog.records if getattr(r, "event", None) == "http.request"]
        assert len(entries) == 1
        entry = entries[0]
        # Concrete path is preserved, but aggregation uses the template.
        assert entry.path == "/api/v1/settings/SOME_KEY"
        assert entry.route_name == "/api/v1/settings/{key}"
        assert entry.method == "GET"
        assert entry.duration_ms >= 0

    def test_health_check_is_not_logged(self, client: TestClient, caplog):
        """The ALB polls it constantly and would drown the inventory."""
        with caplog.at_level(logging.INFO, logger="core.middleware"):
            client.get("/api/health")
        entries = [r for r in caplog.records if getattr(r, "event", None) == "http.request"]
        assert entries == []

    def test_anonymous_request_is_identifiable_as_such(
        self, unauthenticated_client: TestClient, caplog
    ):
        """This is the Phase 0 question: which routes get anonymous traffic."""
        with caplog.at_level(logging.INFO, logger="core.middleware"):
            unauthenticated_client.get("/api/v1/settings?tag_key=a&tag_value=b")
        entry = next(
            r for r in caplog.records if getattr(r, "event", None) == "http.request"
        )
        assert entry.auth_method == "none"
        assert entry.principal is None

    def test_client_application_header_is_captured(self, client: TestClient, caplog):
        """So MCP/ETL/WES traffic is attributable despite generic user agents."""
        with caplog.at_level(logging.INFO, logger="core.middleware"):
            client.get(
                "/api/v1/settings?tag_key=a&tag_value=b",
                headers={"X-Client-Application": "ngs360-mcp-server"},
            )
        entry = next(
            r for r in caplog.records if getattr(r, "event", None) == "http.request"
        )
        assert entry.client_app == "ngs360-mcp-server"


class TestEnvironmentSetting:
    """ENVIRONMENT gates per-tier behaviour and must fail safe"""

    def test_defaults_to_dev(self, monkeypatch):
        monkeypatch.delenv("ENVIRONMENT", raising=False)
        get_settings.cache_clear()
        assert get_settings().ENVIRONMENT == "dev"

    def test_accepts_known_tiers(self, monkeypatch):
        for tier in ("dev", "staging", "prod"):
            monkeypatch.setenv("ENVIRONMENT", tier)
            get_settings.cache_clear()
            assert get_settings().ENVIRONMENT == tier

    def test_is_case_and_whitespace_insensitive(self, monkeypatch):
        monkeypatch.setenv("ENVIRONMENT", "  PROD ")
        get_settings.cache_clear()
        assert get_settings().ENVIRONMENT == "prod"

    def test_unknown_value_falls_back_to_dev(self, monkeypatch):
        """A typo must not silently promote a tier."""
        monkeypatch.setenv("ENVIRONMENT", "production")
        get_settings.cache_clear()
        assert get_settings().ENVIRONMENT == "dev"

    def test_log_format_defaults_to_json(self, monkeypatch):
        monkeypatch.delenv("LOG_FORMAT", raising=False)
        get_settings.cache_clear()
        assert get_settings().LOG_FORMAT == "json"

    def test_log_format_rejects_unknown(self, monkeypatch):
        monkeypatch.setenv("LOG_FORMAT", "xml")
        get_settings.cache_clear()
        assert get_settings().LOG_FORMAT == "json"
