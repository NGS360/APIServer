""" Test cases for RBAC enforcement modes """
import logging
import uuid

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from api.rbac.deps import load_authz, require_permission
from api.rbac.mode import ALWAYS_ENFORCE, RBACMode, effective_mode
from api.rbac.permissions import Permission
from api.rbac.resolver import AuthzContext
from core.config import get_settings
from core.middleware import RequestContextMiddleware


@pytest.fixture
def mode(monkeypatch):
    """Set RBAC_MODE and the tier, clearing the settings cache each time."""
    def _set(value: str, environment: str = "dev"):
        monkeypatch.setenv("RBAC_MODE", value)
        monkeypatch.setenv("ENVIRONMENT", environment)
        get_settings.cache_clear()
        return get_settings().RBAC_MODE
    return _set


class TestModeResolution:

    def test_defaults_to_dry_run(self, monkeypatch):
        monkeypatch.delenv("RBAC_MODE", raising=False)
        get_settings.cache_clear()
        assert get_settings().RBAC_MODE == "dry_run"

    @pytest.mark.parametrize("value", ["off", "dry_run", "enforce"])
    def test_accepts_the_three_valid_values(self, mode, value):
        assert mode(value) == value

    @pytest.mark.parametrize("value", ["enforced", "on", "true", "DRYRUN", "1"])
    def test_an_unrecognised_value_fails_closed(self, mode, value):
        """A typo must never read as 'authorization is off'. The failure mode of
        a misspelling has to be a visible 403, not a silent hole."""
        assert mode(value) == "enforce"

    def test_an_empty_value_is_treated_as_unset(self, mode):
        """Empty is absence, not a typo: `eb setenv RBAC_MODE=` removes the
        variable, and _get_config_value treats empty as unset for every setting
        in this file. Falling through to the default keeps that consistent --
        and the default is the safe end of the range anyway."""
        assert mode("") == "dry_run"

    @pytest.mark.parametrize("value", ["  ENFORCE  ", "Dry_Run", "OFF"])
    def test_is_case_and_whitespace_insensitive(self, mode, value):
        assert mode(value) == value.strip().lower()

    def test_off_is_clamped_to_dry_run_in_prod(self, mode):
        """One `eb setenv` typo must not be able to disable authorization in
        production."""
        assert mode("off", environment="prod") == "dry_run"

    @pytest.mark.parametrize("env", ["dev", "staging"])
    def test_off_is_honoured_outside_prod(self, mode, env):
        assert mode("off", environment=env) == "off"

    def test_enforce_is_unaffected_by_the_prod_clamp(self, mode):
        assert mode("enforce", environment="prod") == "enforce"


class TestAlwaysEnforce:
    """These have near-zero legitimate traffic, so letting them through dry-run
    buys no discovery value while leaving real damage available."""

    @pytest.mark.parametrize("permission", [
        Permission.SETTING_UPDATE, Permission.ROLE_MANAGE,
    ])
    def test_includes_the_critical_permissions(self, permission):
        assert permission in ALWAYS_ENFORCE

    def test_includes_every_delete(self):
        deletes = {p for p in Permission if str(p).endswith(":delete")}
        assert deletes
        assert deletes <= ALWAYS_ENFORCE

    def test_excludes_reads(self):
        assert Permission.PROJECT_READ not in ALWAYS_ENFORCE

    def test_dry_run_escalates_to_enforce(self, mode):
        mode("dry_run")
        assert effective_mode((Permission.PROJECT_DELETE,)) is RBACMode.ENFORCE

    def test_dry_run_is_kept_for_ordinary_permissions(self, mode):
        mode("dry_run")
        assert effective_mode((Permission.PROJECT_READ,)) is RBACMode.DRY_RUN

    def test_any_qualifying_permission_escalates_the_whole_check(self, mode):
        """Passing the check grants the whole route, so one always-enforced
        permission in the set escalates all of it."""
        mode("dry_run")
        assert effective_mode(
            (Permission.PROJECT_READ, Permission.PROJECT_DELETE)
        ) is RBACMode.ENFORCE

    def test_off_is_not_escalated(self, mode):
        """`off` is for local work; only dry-run is escalated."""
        mode("off")
        assert effective_mode((Permission.PROJECT_DELETE,)) is RBACMode.OFF


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

    def test_a_holder_is_allowed_in_every_mode(self, mode):
        for value in ("off", "dry_run", "enforce"):
            mode(value)
            r = _app(Permission.PROJECT_READ, granted=True).get("/guarded")
            assert r.status_code == 200, value

    def test_enforce_denies_a_non_holder(self, mode):
        mode("enforce")
        r = _app(Permission.PROJECT_READ, granted=False).get("/guarded")
        assert r.status_code == 403
        assert "project:read" in r.json()["detail"]

    def test_dry_run_allows_a_non_holder(self, mode):
        """The whole point of the window: observe without breaking callers."""
        mode("dry_run")
        r = _app(Permission.PROJECT_READ, granted=False).get("/guarded")
        assert r.status_code == 200

    def test_off_allows_a_non_holder(self, mode):
        mode("off")
        assert _app(Permission.PROJECT_READ,
                    granted=False).get("/guarded").status_code == 200

    def test_dry_run_still_denies_an_always_enforced_permission(self, mode):
        mode("dry_run")
        r = _app(Permission.PROJECT_DELETE, granted=False).get("/guarded")
        assert r.status_code == 403

    def test_off_does_not_deny_an_always_enforced_permission(self, mode):
        mode("off")
        assert _app(Permission.PROJECT_DELETE,
                    granted=False).get("/guarded").status_code == 200

    def test_the_403_detail_is_a_plain_string(self, mode):
        """The frontend's extractDetail accepts a string or a list of {msg}; a
        dict would fall through to generic copy."""
        mode("enforce")
        detail = _app(Permission.PROJECT_READ,
                      granted=False).get("/guarded").json()["detail"]
        assert isinstance(detail, str)


class TestDecisionLogging:

    def _records(self, caplog, permission, granted, mode_value, mode):
        mode(mode_value)
        with caplog.at_level(logging.INFO):
            _app(permission, granted=granted).get("/guarded")
        return caplog.records

    def test_a_dry_run_refusal_logs_would_deny(self, caplog, mode):
        records = self._records(caplog, Permission.PROJECT_READ, False,
                                "dry_run", mode)
        decision = [r for r in records if getattr(r, "event", None) == "rbac.decision"]
        assert len(decision) == 1
        assert decision[0].rbac_decision == "would_deny"
        assert decision[0].required_permission == "project:read"
        assert decision[0].levelname == "WARNING"

    def test_an_enforced_refusal_logs_deny(self, caplog, mode):
        records = self._records(caplog, Permission.PROJECT_READ, False,
                                "enforce", mode)
        decision = [r for r in records if getattr(r, "event", None) == "rbac.decision"]
        assert decision[0].rbac_decision == "deny"

    def test_an_allow_is_not_logged_as_its_own_line(self, caplog, mode):
        """Allows are carried on the access-log line; a second line per allowed
        request would double the log volume for no added signal."""
        records = self._records(caplog, Permission.PROJECT_READ, True,
                                "enforce", mode)
        assert not [r for r in records
                    if getattr(r, "event", None) == "rbac.decision"]

    def test_the_access_log_carries_the_decision(self, caplog, mode):
        records = self._records(caplog, Permission.PROJECT_READ, False,
                                "dry_run", mode)
        access = [r for r in records if getattr(r, "event", None) == "http.request"]
        assert len(access) == 1
        assert access[0].rbac_decision == "would_deny"
        assert access[0].rbac_mode == "dry_run"
        assert access[0].rbac_checks == 1

    def test_an_unguarded_request_has_no_rbac_fields(self, caplog, mode):
        """Absent, rather than a misleading 'allow', for routes that ran no
        check at all."""
        mode("dry_run")
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
