"""
Authorization dependencies.

These layer *below* get_current_user, so the existing API-key path and the test
dependency overrides keep working untouched. Because get_current_user already
reloads the User row on every request, roles live in the database with no JWT
change -- the token stays {sub, exp, iat, type} and revocation is immediate.

A failed check is a 403. There is no mode flag: authorization either holds or it
does not, and a switch that turns it off is a switch that can be left off. The
dry-run window this rolled out behind lived on the release before this one, and
went out with it -- see docs/RBAC.md.
"""

import logging
import uuid
from typing import Annotated, Literal

from fastapi import Depends, HTTPException, Request, status

from api.auth.deps import OptionalUser, get_current_active_user
from api.auth.models import User
from api.project.deps import ProjectDep
from api.project.models import Project
from api.rbac.permissions import Permission
from api.rbac.resolver import AuthzContext
from core.deps import SessionDep

logger = logging.getLogger(__name__)


def load_authz(
    request: Request,
    session: SessionDep,
    user: Annotated[User, Depends(get_current_active_user)],
) -> AuthzContext:
    """
    Resolve the caller's effective access, once per request.

    FastAPI caches sub-dependency results per request keyed on the callable, and
    every guard below depends on this same function object, so stacking several
    permission checks on one route still costs a single resolution.
    request.state is a second layer for code reaching the resolver outside the
    dependency graph.
    """
    cached: AuthzContext | None = getattr(request.state, "authz", None)
    if cached is not None and cached.user_id == user.id:
        return cached

    context = AuthzContext.for_user(session, user)
    request.state.authz = context
    return context


AuthzDep = Annotated[AuthzContext, Depends(load_authz)]


def load_authz_optional(
    request: Request,
    session: SessionDep,
    user: OptionalUser,
) -> AuthzContext | None:
    """
    The caller's access if there is a caller, None if the request is anonymous.

    For routes that report what the caller may do without *requiring* a caller.
    load_authz cannot be used there: it depends on get_current_active_user, so
    adding it to a route that is still reachable anonymously turns those callers
    into 401s -- which is a Phase 1 decision about closing authentication, not
    something a reporting field should make on its own.

    None and an empty list mean different things downstream. None is "not
    evaluated, because nobody was asking"; an empty list is "evaluated, and this
    caller holds nothing". Collapsing them would report an anonymous request as
    a caller with no access, which is a different and more specific claim.
    """
    if user is None:
        return None

    cached: AuthzContext | None = getattr(request.state, "authz", None)
    if cached is not None and cached.user_id == user.id:
        return cached

    context = AuthzContext.for_user(session, user)
    request.state.authz = context
    return context


OptionalAuthzDep = Annotated[AuthzContext | None, Depends(load_authz_optional)]


def _denied(permissions: tuple[Permission, ...], scope: str | None = None) -> HTTPException:
    """
    Build the 403.

    `detail` stays a plain string: the frontend's extractDetail accepts a string
    or a list of {msg}, and a dict would silently fall through to generic copy.
    Structure goes in sibling keys instead.
    """
    names = ", ".join(str(p) for p in permissions)
    where = f" on {scope}" if scope else ""
    return HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail=f"Missing permission{'s' if len(permissions) > 1 else ''}: {names}{where}",
    )


def _decide(
    request: Request,
    granted: bool,
    permissions: tuple[Permission, ...],
    scope: str | None,
) -> None:
    """
    Record one check's result, and raise if it failed.

    Every check emits a decision, allow as well as deny. Knowing only the
    refusals tells you nothing about which principals a permission actually lets
    through, and that is the question an access review asks.

    Refusals log at WARNING so they are findable without trawling. A 403 here is
    ordinary -- it is what a permission is for -- so the line is a record, not an
    alarm.
    """
    decision = "allow" if granted else "deny"

    record = {
        "rbac_decision": decision,
        "required_permission": ",".join(str(p) for p in permissions),
        "scope": scope,
    }
    # The access-log line in RequestContextMiddleware picks these up, so a
    # single CloudWatch query can join a decision to the request that caused it.
    decisions = getattr(request.state, "rbac_decisions", None)
    if decisions is None:
        decisions = []
        request.state.rbac_decisions = decisions
    decisions.append(record)

    if not granted:
        logger.warning(
            "rbac %s: %s", decision, record["required_permission"],
            extra={
                "event": "rbac.decision",
                "principal": getattr(request.state, "principal", None),
                "auth_method": getattr(request.state, "auth_method", None),
                "request_id": getattr(request.state, "request_id", None),
                "method": request.method,
                "path": request.url.path,
                **record,
            },
        )

        raise _denied(permissions, scope=scope)


def require_permission(
    *permissions: Permission, mode: Literal["all", "any"] = "all"
):
    """
    Global-plane guard.

    Returns the AuthzContext so a route needing both the check and the context
    does not resolve twice.
    """
    if not permissions:
        raise ValueError("require_permission needs at least one permission")

    def dependency(request: Request, authz: AuthzDep) -> AuthzContext:
        check = all if mode == "all" else any
        _decide(request, check(authz.has(p) for p in permissions), permissions,
                scope=None)
        return authz

    # Tag the closure so a route's requirements can be read back off the
    # dependency graph. The route-coverage test uses this to prove no route is
    # left unguarded by accident, and it is the obvious source for a future
    # "what does this endpoint need" admin endpoint.
    dependency.rbac_permissions = permissions
    dependency.rbac_plane = "global"
    return dependency


def require_project_permission(
    *permissions: Permission, mode: Literal["all", "any"] = "all"
):
    """
    Project-plane guard.

    Returns the Project, making it a drop-in replacement for ProjectDep: an
    existing route converts by swapping one annotation, with its body untouched.

    Declaring ProjectDep as a sub-dependency is what guarantees the project is
    resolved -- and its 404 raised -- before this check runs.
    """
    if not permissions:
        raise ValueError("require_project_permission needs at least one permission")
    unscopable = [p for p in permissions if p not in _project_scopable()]
    if unscopable:
        raise ValueError(
            f"not project-scopable, so a project role can never grant them: "
            f"{[str(p) for p in unscopable]}"
        )

    def dependency(
        request: Request, project: ProjectDep, authz: AuthzDep
    ) -> Project:
        check = all if mode == "all" else any
        _decide(
            request,
            check(authz.has_in_project(p, project.id) for p in permissions),
            permissions,
            scope=f"project {project.project_id}",
        )
        return project

    dependency.rbac_permissions = permissions
    dependency.rbac_plane = "project"
    return dependency


def _project_scopable():
    # Imported lazily to keep this module importable if the catalog grows a
    # dependency on anything here.
    from api.rbac.permissions import PROJECT_SCOPABLE

    return PROJECT_SCOPABLE


def project_scope(permission: Permission = Permission.PROJECT_READ):
    """
    Yields the project ids a caller may see, or None for unrestricted.

    For list endpoints, which must return a narrower list rather than a 403. The
    value is plain data so services keep taking primitives rather than User
    objects, matching the existing convention.

    Callers must filter in the SQL WHERE clause, not on the page slice --
    post-filtering a page breaks total_items and has_next.
    """

    def dependency(authz: AuthzDep) -> set[uuid.UUID] | None:
        return authz.visible_project_ids(permission)

    return dependency


ProjectScopeDep = Annotated[set[uuid.UUID] | None, Depends(project_scope())]
