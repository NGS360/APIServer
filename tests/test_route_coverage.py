"""
Every route is accounted for: guarded, deliberately public, self-service, or
explicitly recorded as still awaiting authentication closure.

This is the test that stops drift. Without it a new route added without a guard
is invisible -- it simply works, for everyone, and nobody notices until an
audit. The lists below are exhaustive by construction: the assertion is an
equality, so adding an unguarded route fails (an unexpected entry) and guarding
one also fails (a stale entry). Both directions have to be a deliberate edit.
"""
import os

import pytest

os.environ.setdefault("SQLALCHEMY_DATABASE_URI", "sqlite://")

from core.middleware import _build_route_path_map  # noqa: E402
from main import app  # noqa: E402


# Reachable without credentials, and necessarily so: these are how a caller
# obtains credentials in the first place.
PUBLIC = {
    "GET /api/v1/auth/oauth/providers",
    "GET /api/v1/auth/oauth/{provider}/authorize",
    "GET /api/v1/auth/oauth/{provider}/callback",
    "POST /api/v1/auth/login",
    "POST /api/v1/auth/logout",
    "POST /api/v1/auth/password-reset/confirm",
    "POST /api/v1/auth/password-reset/request",
    "POST /api/v1/auth/refresh",
    "POST /api/v1/auth/register",
    "POST /api/v1/auth/resend-verification",
    "POST /api/v1/auth/verify-email",
}

# Authenticated, but acting only on the caller's own account. A permission here
# would be one every user necessarily holds, which is not a permission -- it is
# a line of code that always returns True.
SELF_SERVICE = {
    "DELETE /api/v1/auth/api-keys/{key_id}",
    "DELETE /api/v1/auth/oauth/{provider}/unlink",
    "GET /api/v1/auth/api-keys",
    "GET /api/v1/auth/me",
    "GET /api/v1/rbac/me",
    "POST /api/v1/auth/api-keys",
    "POST /api/v1/auth/api-keys/{key_id}/revoke",
    "POST /api/v1/auth/oauth/{provider}/link",
    "POST /api/v1/auth/password/change",
}

# Anonymous today, and cannot be guarded until authentication is closed on them.
#
# require_permission depends on get_current_active_user, so attaching a guard to
# one of these returns 401 to today's anonymous callers -- before any mode check
# runs. RBAC_MODE=dry_run does not soften that, which is why these are Phase 1
# work (close authentication, with the consumer migrations that implies) and not
# Phase 4 work. See docs/RBAC.md.
#
# This set only ever shrinks. Removing an entry means that route now requires a
# caller to authenticate, which is a breaking change for whoever calls it today.
AWAITING_AUTHENTICATION = {
    "DELETE /api/v1/pipelines/{pipeline_id}/workflows/{workflow_id}",
    "DELETE /api/v1/qcmetrics/{qcrecord_id}",
    "DELETE /api/v1/runs/{run_id}/samples/{sample_id}",
    "DELETE /api/v1/vendors/{vendor_id}",
    "DELETE /api/v1/workflows/{workflow_id}/aliases/{alias}",
    "DELETE /api/v1/workflows/{workflow_id}/versions/{version_num}"
    "/deployments/{deployment_id}",
    "GET /api/v1/actions/configs",
    "GET /api/v1/actions/options",
    "GET /api/v1/actions/platforms",
    "GET /api/v1/actions/types",
    "GET /api/v1/files",
    "GET /api/v1/files/download",
    "GET /api/v1/files/list",
    "GET /api/v1/files/{file_id}",
    "GET /api/v1/files/{file_id}/versions",
    "GET /api/v1/jobs",
    "GET /api/v1/jobs/{job_id}",
    "GET /api/v1/jobs/{job_id}/log",
    "GET /api/v1/jobs/{job_id}/log/paginated",
    "GET /api/v1/manifest",
    "GET /api/v1/pipelines",
    "GET /api/v1/pipelines/{pipeline_id}",
    "GET /api/v1/platforms",
    "GET /api/v1/platforms/{name}",
    "GET /api/v1/projects",
    "GET /api/v1/projects/attributes",
    "GET /api/v1/projects/search",
    "GET /api/v1/projects/{project_id}",
    "GET /api/v1/projects/{project_id}/samples",
    "GET /api/v1/qcmetrics/search",
    "GET /api/v1/qcmetrics/{qcrecord_id}",
    "GET /api/v1/runs",
    "GET /api/v1/runs/demultiplex",
    "GET /api/v1/runs/demultiplex/{workflow_id}",
    "GET /api/v1/runs/search",
    "GET /api/v1/runs/{run_id}",
    "GET /api/v1/runs/{run_id}/metrics",
    "GET /api/v1/runs/{run_id}/samples",
    "GET /api/v1/runs/{run_id}/samplesheet",
    "GET /api/v1/samples/search",
    "GET /api/v1/search",
    "GET /api/v1/settings",
    "GET /api/v1/settings/{key}",
    "GET /api/v1/vendors",
    "GET /api/v1/vendors/{vendor_id}",
    "GET /api/v1/workflows",
    "GET /api/v1/workflows/{workflow_id}",
    "GET /api/v1/workflows/{workflow_id}/aliases",
    "GET /api/v1/workflows/{workflow_id}/deployments",
    "GET /api/v1/workflows/{workflow_id}/versions",
    "GET /api/v1/workflows/{workflow_id}/versions/{version_num}",
    "GET /api/v1/workflows/{workflow_id}/versions/{version_num}/deployments",
    "PATCH /api/v1/projects/{project_id}",
    "POST /api/v1/actions/config/validate",
    "POST /api/v1/files",
    "POST /api/v1/files/upload",
    "POST /api/v1/jobs",
    "POST /api/v1/manifest",
    "POST /api/v1/manifest/validate",
    "POST /api/v1/platforms",
    "POST /api/v1/projects/search",
    "POST /api/v1/qcmetrics/search",
    "POST /api/v1/runs",
    "POST /api/v1/runs/search",
    "POST /api/v1/runs/{run_id}/samplesheet",
    "POST /api/v1/samples/reindex",
    "POST /api/v1/samples/search",
    "POST /api/v1/vendors",
    "PUT /api/v1/jobs/{job_id}",
    "PUT /api/v1/projects/{project_id}",
    "PUT /api/v1/projects/{project_id}/samples/{sample_id}",
    "PUT /api/v1/runs/{run_id}",
    "PUT /api/v1/vendors/{vendor_id}",
}


def _walk_routes():
    """
    Yield (key, guard_permissions) for every route under /api/v1.

    This FastAPI version does not flatten included routers, so the app holds
    wrappers whose inner routes carry router-relative paths; the same map the
    access log uses resolves them to full templates.
    """
    mapping = _build_route_path_map(app)
    for route in app.routes:
        inner = [route]
        contexts = getattr(route, "effective_route_contexts", None)
        if callable(contexts):
            inner = [c.original_route for c in contexts()]
        for r in inner:
            if not hasattr(r, "dependant"):
                continue
            path = mapping.get(id(r), getattr(r, "path", ""))
            if not path.startswith("/api/v1"):
                continue

            guards = []
            stack = list(r.dependant.dependencies)
            while stack:
                d = stack.pop()
                found = getattr(d.call, "rbac_permissions", None)
                if found:
                    guards.append((getattr(d.call, "rbac_plane"), tuple(found)))
                stack.extend(d.dependencies)

            for method in sorted(r.methods - {"HEAD", "OPTIONS"}):
                yield f"{method} {path}", guards


ROUTES = dict(_walk_routes())
GUARDED = {k for k, guards in ROUTES.items() if guards}
UNGUARDED = {k for k, guards in ROUTES.items() if not guards}


def _permissions(key):
    return [p for _, perms in ROUTES[key] for p in perms]


def test_every_route_is_classified():
    """
    The exhaustive check. Adding a route without a guard fails here, and so does
    guarding one without removing it from the list below.
    """
    expected = PUBLIC | SELF_SERVICE | AWAITING_AUTHENTICATION
    unexpected = UNGUARDED - expected
    stale = expected - UNGUARDED

    assert not unexpected, (
        "These routes have no permission guard and are not classified. Either "
        "guard them, or add them to the appropriate set in this file with a "
        f"reason: {sorted(unexpected)}"
    )
    assert not stale, (
        "These are listed as unguarded but now carry a guard. Remove them from "
        f"the list: {sorted(stale)}"
    )


def test_the_three_classifications_do_not_overlap():
    assert not PUBLIC & SELF_SERVICE
    assert not PUBLIC & AWAITING_AUTHENTICATION
    assert not SELF_SERVICE & AWAITING_AUTHENTICATION


def test_no_classified_route_is_also_guarded():
    """A guarded route must not linger in a list that says it is not."""
    overlap = GUARDED & (PUBLIC | SELF_SERVICE | AWAITING_AUTHENTICATION)
    assert not overlap, sorted(overlap)


def test_guard_count_is_recorded():
    """
    Pins the size of the guarded surface so growth is visible in review rather
    than incidental.
    """
    assert len(GUARDED) == 36


def test_the_authentication_backlog_only_shrinks():
    """
    Phase 1's remaining work, as a number.

    Lowering this is a breaking change for whoever calls the route anonymously,
    so it should only ever move down, deliberately, with the consumer migration
    that justifies it.
    """
    assert len(AWAITING_AUTHENTICATION) == 73


@pytest.mark.parametrize("key", sorted(GUARDED))
def test_every_guard_names_a_real_catalog_permission(key):
    """A guard citing a permission no role can hold is a permanent 403."""
    from api.rbac.permissions import ALL_PERMISSIONS

    for permission in _permissions(key):
        assert permission in ALL_PERMISSIONS, f"{key} requires unknown {permission}"


@pytest.mark.parametrize("key", sorted(GUARDED))
def test_project_plane_guards_use_scopable_permissions(key):
    """
    A project-plane guard citing a permission the project plane cannot grant
    would be unsatisfiable by any project role.
    """
    from api.rbac.permissions import PROJECT_SCOPABLE

    for plane, perms in ROUTES[key]:
        if plane != "project":
            continue
        for permission in perms:
            assert permission in PROJECT_SCOPABLE, (
                f"{key} is guarded on the project plane by {permission}, which "
                "no project role can carry"
            )


def test_project_scoped_paths_use_the_project_plane():
    """
    A path carrying {project_id} should be checked against that project, not
    globally -- otherwise a grant on one project silently authorises every
    other. project:create is the exception: it runs before a project exists.
    """
    from api.rbac.permissions import Permission

    wrong = []
    for key in sorted(GUARDED):
        if "{project_id}" not in key:
            continue
        for plane, perms in ROUTES[key]:
            if plane == "project":
                continue
            if set(perms) <= {Permission.PROJECT_CREATE}:
                continue
            wrong.append((key, plane, [str(p) for p in perms]))
    assert not wrong, wrong
