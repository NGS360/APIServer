"""
Test cases for guard behaviour and decision logging.

There is no enforcement mode: a failed check is a 403, always. What is left to
pin is the shape of that refusal -- the status, the detail the frontend parses,
and the log record an access review reads.
"""
import logging
import uuid

from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from api.rbac.deps import load_authz, require_permission
from api.rbac.permissions import Permission
from api.rbac.resolver import AuthzContext
from core.middleware import RequestContextMiddleware


def _app(permission: Permission, *, granted: bool) -> TestClient:
    """A one-route app whose caller holds, or does not hold, `permission`."""
    app = FastAPI()
    app.add_middleware(RequestContextMiddleware)

    @app.get("/guarded")
    def guarded(_=Depends(require_permission(permission))):
        return {"reached": True}

    def fake_authz():
        return AuthzContext(
            user_id=uuid.uuid4(), username="tester", is_superuser=False,
            global_permissions=frozenset({str(permission)} if granted else set()),
            session=None,
        )

    app.dependency_overrides[load_authz] = fake_authz
    return TestClient(app)


class TestGuardBehaviour:

    def test_a_holder_is_allowed(self):
        assert _app(Permission.PROJECT_READ,
                    granted=True).get("/guarded").status_code == 200

    def test_a_non_holder_is_denied(self):
        r = _app(Permission.PROJECT_READ, granted=False).get("/guarded")
        assert r.status_code == 403
        assert "project:read" in r.json()["detail"]

    def test_a_low_risk_read_is_denied_like_anything_else(self):
        """
        No permission is exempt.

        There used to be an always-enforced set, because dry-run allowed what it
        would otherwise refuse and some permissions were too dangerous to leave
        open for the length of the rollout. With enforcement unconditional the
        distinction has nothing left to mean, and `project:read` -- the lowest
        risk in the catalog -- refuses exactly as `role:manage` does.
        """
        assert _app(Permission.PROJECT_READ,
                    granted=False).get("/guarded").status_code == 403
        assert _app(Permission.ROLE_MANAGE,
                    granted=False).get("/guarded").status_code == 403

    def test_the_403_detail_is_a_plain_string(self):
        """The frontend's extractDetail accepts a string or a list of {msg}; a
        dict would fall through to generic copy."""
        detail = _app(Permission.PROJECT_READ,
                      granted=False).get("/guarded").json()["detail"]
        assert isinstance(detail, str)


class TestDecisionLogging:

    def _records(self, caplog, permission, granted):
        with caplog.at_level(logging.INFO):
            _app(permission, granted=granted).get("/guarded")
        return caplog.records

    def test_a_refusal_logs_deny_at_warning(self, caplog):
        records = self._records(caplog, Permission.PROJECT_READ, False)
        decision = [r for r in records if getattr(r, "event", None) == "rbac.decision"]
        assert len(decision) == 1
        assert decision[0].rbac_decision == "deny"
        assert decision[0].required_permission == "project:read"
        assert decision[0].levelname == "WARNING"

    def test_an_allow_is_not_logged_as_its_own_line(self, caplog):
        """Allows are carried on the access-log line; a second line per allowed
        request would double the log volume for no added signal."""
        records = self._records(caplog, Permission.PROJECT_READ, True)
        assert not [r for r in records
                    if getattr(r, "event", None) == "rbac.decision"]

    def test_the_access_log_carries_the_decision(self, caplog):
        records = self._records(caplog, Permission.PROJECT_READ, False)
        access = [r for r in records if getattr(r, "event", None) == "http.request"]
        assert len(access) == 1
        assert access[0].rbac_decision == "deny"
        assert access[0].rbac_checks == 1

    def test_the_access_log_carries_an_allow_too(self, caplog):
        """
        Knowing only the refusals tells you nothing about which principals a
        permission actually lets through, which is the question an access review
        asks.
        """
        records = self._records(caplog, Permission.PROJECT_READ, True)
        access = [r for r in records if getattr(r, "event", None) == "http.request"]
        assert access[0].rbac_decision == "allow"

    def test_an_unguarded_request_has_no_rbac_fields(self, caplog):
        """Absent, rather than a misleading 'allow', for routes that ran no
        check at all."""
        app = FastAPI()
        app.add_middleware(RequestContextMiddleware)

        @app.get("/open")
        def open_route():
            return {}

        with caplog.at_level(logging.INFO):
            TestClient(app).get("/open")
        access = [r for r in caplog.records
                  if getattr(r, "event", None) == "http.request"]
        assert not hasattr(access[0], "rbac_decision")
