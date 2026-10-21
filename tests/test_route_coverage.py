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
import re

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

# Authenticated, but carrying no permission guard yet.
#
# Renamed from AUTHENTICATED_BUT_UNGUARDED on 2026-10-14. Authentication is no
# longer what these are waiting for: every feature router now requires a caller
# (see main.py), so each of these returns 401 to an anonymous request. What they
# still lack is a *permission* guard, which is the remaining work and is now
# ordinary Phase 4 work rather than blocked on consumer migrations.
#
# The old name encoded a real constraint while it lasted: require_permission
# depends on get_current_active_user, so attaching a guard to an anonymous route
# returned 401 before any mode check ran, and RBAC_MODE=dry_run did not soften
# it. Closing authentication first is what removed that ordering problem.
#
# This set only ever shrinks. Removing an entry means that route now has a
# permission guard.
AUTHENTICATED_BUT_UNGUARDED: set[str] = set()


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
    expected = PUBLIC | SELF_SERVICE | AUTHENTICATED_BUT_UNGUARDED
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
    assert not PUBLIC & AUTHENTICATED_BUT_UNGUARDED
    assert not SELF_SERVICE & AUTHENTICATED_BUT_UNGUARDED


def test_no_classified_route_is_also_guarded():
    """A guarded route must not linger in a list that says it is not."""
    overlap = GUARDED & (PUBLIC | SELF_SERVICE | AUTHENTICATED_BUT_UNGUARDED)
    assert not overlap, sorted(overlap)


def test_guard_count_is_recorded():
    """
    Pins the size of the guarded surface so growth is visible in review rather
    than incidental.

    86 -> 87: GET /jobs/stats/submitters, which backs the Submitted By filter on
    the jobs tables. Guarded on job:read from the start -- the unguarded GET /jobs
    next to it is backlog, not precedent, and a route whose only caller is the
    authenticated UI never needs to join it.

    89 -> 115: the last 26, as one batch. Every permission involved is in the
    default role, so none of them refuses anyone -- the batch exists to finish
    the decision record and empty this category, not to restrict. Two are worth
    noting: GET /files/list is guarded on file:browse, which until now was an
    inert permission no route checked, and POST /files/upload on file:create,
    matching the JSON POST /files beside it.

    87 -> 89: GET /projects/{project_id} on project:read and
    GET /projects/{project_id}/samples on sample:read. Both permissions are in
    the default role, so neither refuses anyone who could reach them before.
    They are guarded for the other thing require_project_permission does --
    a project marked `restricted` requires membership, and that check lives in
    the guard. Until now a locked-down project still handed its metadata and
    sample list to any authenticated caller, which made `restricted` a
    half-measure. These two are the routes that make it whole.

    115 -> 118 with the user administration API: GET /rbac/users, GET
    /rbac/users/{username}/access and PATCH /users/{username}.

    118 -> 119: PUT /projects/{project_id}/restriction, which moved the
    `restricted` flag off the project update routes. Those two take
    project:update, which is metadata authority; closing a project to everyone
    outside its member list is not a metadata edit and takes
    project:manage_members instead.
    """
    assert len(GUARDED) == 119


def test_the_authentication_backlog_only_shrinks():
    """
    Phase 1's remaining work, as a number.

    Lowering this is a breaking change for whoever calls the route anonymously,
    so it should only ever move down, deliberately, with the consumer migration
    that justifies it.

    73 -> 72: PUT /jobs/{job_id} closed once the Omics event processor started
    sending its API key, which left no anonymous caller on it in any tier.

    72 -> 69: GET /projects, GET /projects/attributes and GET /samples/search,
    once Airflow finished adopting its key. Measured over the clean log window
    they carried 61,938, 983 and 12 authenticated requests and zero anonymous
    ones. GET /files/download and GET /projects/search were candidates in the
    same pass and were deliberately left open -- each still has a live anonymous
    python-requests caller, of one and nine requests respectively, and one
    request is not zero.

    69 -> 68: GET /files/download, on 2026-09-09. This one had a second reason
    to stay open beyond anonymous callers -- the UI used it as a plain link, and
    a browser following a link cannot send a token, so guarding it would have
    401'd real downloads. That reason expired: the frontend now fetches
    /files/download-url with its token and navigates itself, and the deployed
    bundle contains no reference to this route. Browser traffic in the 30 days to
    09-09 was 41 requests, 39 of them a single bulk download on 08-15 (most
    likely a tab holding a pre-fix bundle), 2 on 09-04, none since.

    The anonymous python-requests caller noted above is still the accepted cost,
    and it is now measurable rather than estimated: the guard emits a decision
    record, so the residual shows up as 401s on this route instead of being
    inferred from user agents.

    68 -> 54: fourteen routes in one pass, 2026-09-11. The first batch sized by
    resolving *every* observed caller on *every* candidate route against the
    permission its guard would require, rather than by checking anonymous
    traffic alone. That corrected the count in both directions -- it found ten
    demux operators lacking run:update who would have started receiving 403s,
    and three apparent gaps that were a credential revoked on 09-04 and
    therefore incapable of calling again.

    The arithmetic, which is the part worth keeping:

      68  awaiting
     -23  no traffic at all in the clean window (closable, but blind)
     -28  anonymous or invalid-jwt traffic (blocked on a consumer)
      ---
      17  candidates
      -3  a caller still lacks the guard after the 09-11 grants
      ---
      14  closed here

    Note 17 candidates, not 21. An earlier count read auth_method=jwt as
    authenticated; check 3 removes four routes, one of them
    GET /jobs/{job_id}/log/paginated with 6,951 invalid-jwt requests against
    7,269 valid ones -- a consumer that looks migrated in any query filtering on
    auth_method alone.

    54 -> 51: the last three of those 17 candidates, 2026-09-15. Each had been
    held back on exactly one caller lacking one permission, and all three were
    resolved by grants rather than by code:

      POST /runs                          run:create    a service account
      PUT /projects/{id}/samples/{id}     sample:update a service account
      POST /runs/{run_id}/samplesheet     run:update    one user

    The first two came from service_account holding each verb's update without
    its create, or the reverse -- an asymmetry that described no real workflow
    and was hit by two different accounts. The third was a demux operator missed
    from the original list of eleven; they submit demux jobs and write
    samplesheets, so demux_operator was the right role rather than a widening.

    With these, every candidate that passed checks 1-3 is closed. What remains
    in this list is 23 routes with no observed traffic and 28 blocked on a
    consumer, and neither group is closable by anything we control.

    51 -> 28: those twenty-three, 2026-09-18, once the clean window since the
    August log gaps reached 30 days. Twenty-two had *no traffic at all* across
    it; the twenty-third, GET /runs/demultiplex/{workflow_id}, became closable
    when its single invalid-JWT caller stopped.

    Silence is the weakest evidence this list has been reduced on -- it shows
    nobody called, not that a future caller would authenticate. What makes it
    acceptable is a second measurement rather than the first: for twelve of the
    twenty-three the guard requires a permission `member` already holds, so
    enforcement cannot refuse any authenticated caller at all. Those twelve are
    closed against anonymous access and nothing else.

    The other eleven are catalog writes and deletes -- vendors, platforms,
    pipeline-workflow links, workflow aliases and deployments, sample reindex.
    Four enforce immediately because their permissions are graduated or are
    :delete -- pipeline:update, qcrecord:delete, vendor:delete, workflow:update.
    A surprise caller there gets a 403 rather than a log line, accepted because
    all four are administrative with zero traffic for a month. The other seven
    log.

    run:associate is deliberately among the seven that log: it has a live
    refusing caller (a run-metrics service account), so guarding
    DELETE /runs/{run_id}/samples/{sample_id} on it must not enforce yet.

    28 -> 26 on 2026-10-15: the two project reads were guarded, which is what
    gives `restricted` effect over reads.

    26 -> 0 on 2026-10-15: the remainder, as one batch. The category is now
    empty, and this assertion is what keeps it that way -- a new route arrives
    either guarded, or listed in PUBLIC or SELF_SERVICE with a reason.
    """
    assert len(AUTHENTICATED_BUT_UNGUARDED) == 0


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


def test_only_the_authentication_routes_are_reachable_anonymously():
    """
    The partition, asserted by *behaviour* rather than by introspection.

    This is deliberately not a walk of the dependency graph, and the reason is
    worth recording. FastAPI does not flatten included routers in this version,
    so `include_router(dependencies=...)` attaches to the wrapper while
    `effective_route_contexts()` hands back the inner route -- which still looks
    unauthenticated. A graph walk written the obvious way reported all 39
    anonymous routes as *still* anonymous after they had been closed, and the
    only thing that showed otherwise was sending a request.

    So: send requests. One per route, with no credentials, asserting that
    everything outside PUBLIC refuses. A 401 or 403 is a pass; anything that
    reaches the handler -- including a 422 for a bad body, or a 404 for a
    missing id -- means the route ran for an anonymous caller.
    """
    from fastapi.testclient import TestClient

    from main import app

    client = TestClient(app, raise_server_exceptions=False)
    reached_handler = []

    for key in sorted(ROUTES):
        if key in PUBLIC:
            continue
        method, path = key.split(" ", 1)
        # Any placeholder will do; authentication is checked before the handler
        # resolves a path parameter.
        concrete = re.sub(r"\{[^}]+\}", "x", path)
        response = client.request(method, concrete)
        if response.status_code not in (401, 403):
            reached_handler.append("%s %s -> %s" % (method, concrete,
                                                    response.status_code))

    assert not reached_handler, (
        "these routes ran for an anonymous caller:\n  "
        + "\n  ".join(reached_handler)
    )


def test_the_public_routes_are_still_public():
    """The other half: closing everything else must not close the front door."""
    from fastapi.testclient import TestClient

    from main import app

    client = TestClient(app, raise_server_exceptions=False)
    refused = []
    for key in sorted(PUBLIC):
        method, path = key.split(" ", 1)
        concrete = re.sub(r"\{[^}]+\}", "x", path)
        response = client.request(method, concrete)
        if response.status_code in (401, 403):
            refused.append("%s %s -> %s" % (method, concrete,
                                            response.status_code))
    assert not refused, (
        "the authentication surface must stay reachable:\n  " + "\n  ".join(refused)
    )


def test_no_guard_is_hiding_in_a_handler_signature():
    """
    A guard written into the handler's parameters instead of the decorator is
    valid Python, does nothing, and adds a bogus `dependencies` query parameter
    to the route.

    This is not hypothetical. Guarding the last 26 routes was done by script,
    and two of them -- GET /search and GET /runs/demultiplex -- landed in the
    signature because their decorators were single-line and the insertion point
    was computed from the next closing paren. flake8 passed, the suite passed,
    and the routes were unguarded. The route-coverage counts caught one of them;
    this catches the shape directly.

    Uses the AST rather than a line scan: a first attempt at a textual detector
    reported 19 hits, 18 of them false, because one-line `def`s left its state
    machine convinced it was still inside a signature.
    """
    import ast
    import glob

    offenders = []
    for path in sorted(glob.glob("api/**/routes.py", recursive=True)):
        with open(path) as handle:
            tree = ast.parse(handle.read(), path)
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            args = node.args
            names = [a.arg for a in
                     list(args.posonlyargs) + list(args.args) + list(args.kwonlyargs)]
            if "dependencies" in names:
                offenders.append("%s:%d %s" % (path, node.lineno, node.name))

    assert not offenders, (
        "these handlers take `dependencies` as a parameter, which means the "
        "guard is in the signature rather than the decorator and is doing "
        "nothing:\n  " + "\n  ".join(offenders)
    )
