"""
Authorization dependencies.

These layer *below* get_current_user, so the existing API-key path and the test
dependency overrides keep working untouched. Because get_current_user already
reloads the User row on every request, roles live in the database with no JWT
change -- the token stays {sub, exp, iat, type} and revocation is immediate.

Nothing here is attached to a route yet. Phase 4 does that, behind a mode flag.
"""

import uuid
from typing import Annotated, Literal

from fastapi import Depends, HTTPException, Request, status

from api.auth.deps import get_current_active_user
from api.auth.models import User
from api.project.deps import ProjectDep
from api.project.models import Project
from api.rbac.permissions import Permission
from api.rbac.resolver import AuthzContext
from core.deps import SessionDep


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

    def dependency(authz: AuthzDep) -> AuthzContext:
        check = all if mode == "all" else any
        if not check(authz.has(p) for p in permissions):
            raise _denied(permissions)
        return authz

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

    def dependency(project: ProjectDep, authz: AuthzDep) -> Project:
        check = all if mode == "all" else any
        if not check(authz.has_in_project(p, project.id) for p in permissions):
            raise _denied(permissions, scope=f"project {project.project_id}")
        return project

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
