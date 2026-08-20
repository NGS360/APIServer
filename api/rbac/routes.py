"""
The RBAC administration API: roles, permissions, grants, and who holds what.

Every route here carries both a require_permission guard and CurrentSuperuser,
which reads like belt and braces and is not. RBAC_MODE defaults to dry_run,
where a failed permission check is logged and then allowed through, so until the
mode reaches enforce the superuser dependency is the only thing standing between
this router and any authenticated caller. Since this router is where access is
granted and where everybody's access can be read, that is not a gap to leave
open for the length of a rollout. Removing the dependency is a Phase 5 change,
made together with the mode.

Note that role:manage is `critical` risk, so ALWAYS_ENFORCE already escalates
the mutations to real enforcement even in dry-run; it is the reads that depend
on the superuser dependency.

Project membership is deliberately not here -- it lives on the project router so
that project owners can self-serve. See docs/RBAC.md.
"""

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlmodel import select

from api.auth.deps import CurrentActiveUser, CurrentSuperuser
from api.rbac import services
from api.rbac.models import (
    GrantRoleRequest,
    PermissionPublic,
    Role,
    RoleCreate,
    RolePermission,
    RolePermissionsUpdate,
    RolePublic,
    UserAccessPublic,
    UsersAdminPublic,
)
from api.rbac.deps import require_permission
from api.rbac.permissions import CATALOG, Permission
from api.rbac.resolver import AuthzContext, global_role_names
from core.deps import SessionDep

router = APIRouter(prefix="/rbac", tags=["RBAC Endpoints"])


def _role_public(session: SessionDep, role: Role) -> RolePublic:
    permissions = session.exec(
        select(RolePermission.permission).where(RolePermission.role_id == role.id)
    ).all()
    return RolePublic(
        id=role.id,
        name=role.name,
        display_name=role.display_name,
        description=role.description,
        scope=role.scope,
        is_builtin=role.is_builtin,
        permissions=sorted(permissions),
    )


@router.get(
    "/permissions",
    response_model=list[PermissionPublic],
    summary="The permission catalog (superuser only)",
    dependencies=[Depends(require_permission(Permission.ROLE_READ))],
)
def list_permissions(current_user: CurrentSuperuser) -> list[PermissionPublic]:
    """
    Every permission the API recognises, with its risk and scopability.

    Served from the code-level catalog rather than the database: a permission
    only means something if a route checks it, so this is the authoritative list
    of what can actually be granted.
    """
    return [
        PermissionPublic(
            permission=str(permission),
            resource=spec.resource,
            description=spec.description,
            project_scopable=spec.project_scopable,
            risk=spec.risk,
        )
        for permission, spec in sorted(CATALOG.items(), key=lambda kv: str(kv[0]))
    ]


@router.get(
    "/roles",
    response_model=list[RolePublic],
    summary="List roles (superuser only)",
    dependencies=[Depends(require_permission(Permission.ROLE_READ))],
)
def list_roles(session: SessionDep, current_user: CurrentSuperuser) -> list[RolePublic]:
    roles = session.exec(select(Role).order_by(Role.scope, Role.name)).all()
    return [_role_public(session, role) for role in roles]


@router.get(
    "/roles/{name}",
    response_model=RolePublic,
    summary="Get one role (superuser only)",
    responses={404: {"description": "Role not found"}},
    dependencies=[Depends(require_permission(Permission.ROLE_READ))],
)
def get_role(
    session: SessionDep, name: str, current_user: CurrentSuperuser
) -> RolePublic:
    role = session.exec(select(Role).where(Role.name == name)).first()
    if role is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"No role named {name}"
        )
    return _role_public(session, role)


@router.get(
    "/me",
    summary="The calling user's own effective access",
)
def get_my_access(session: SessionDep, current_user: CurrentActiveUser) -> dict:
    """
    What the caller can do, so a UI can decide which controls to render rather
    than rendering everything and absorbing 403s.

    Global permissions only. Project-scoped permissions are deliberately not
    inlined -- with a five-figure project count the payload would be unbounded --
    they belong on the project detail response instead.
    """
    authz = AuthzContext.for_user(session, current_user)
    return {
        "username": current_user.username,
        "is_superuser": authz.is_superuser,
        "global_roles": global_role_names(session, current_user.id),
        "global_permissions": authz.effective_permissions(),
    }


# --- role mutations -------------------------------------------------------

@router.post(
    "/roles",
    response_model=RolePublic,
    status_code=status.HTTP_201_CREATED,
    summary="Create a custom role (superuser only)",
    responses={409: {"description": "A role with that name exists"}},
    dependencies=[Depends(require_permission(Permission.ROLE_MANAGE))],
)
def create_role(
    session: SessionDep, body: RoleCreate, current_user: CurrentSuperuser
) -> RolePublic:
    """
    Custom roles are how "contributor without delete" and similar variants are
    served, which is the reason roles are rows rather than code.
    """
    role = services.create_role(
        session,
        name=body.name,
        display_name=body.display_name,
        description=body.description,
        scope=body.scope,
        permissions=body.permissions,
    )
    return _role_public(session, role)


@router.patch(
    "/roles/{name}",
    response_model=RolePublic,
    summary="Replace a custom role's permissions (superuser only)",
    responses={
        404: {"description": "Role not found"},
        409: {"description": "Builtin roles are code-defined"},
    },
    dependencies=[Depends(require_permission(Permission.ROLE_MANAGE))],
)
def update_role_permissions(
    session: SessionDep, name: str, body: RolePermissionsUpdate,
    current_user: CurrentSuperuser,
) -> RolePublic:
    role = services.get_role_or_404(session, name)
    role = services.set_role_permissions(session, role, body.permissions)
    return _role_public(session, role)


@router.delete(
    "/roles/{name}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a custom role (superuser only)",
    responses={409: {"description": "Builtin, or still granted"}},
    dependencies=[Depends(require_permission(Permission.ROLE_MANAGE))],
)
def delete_role(
    session: SessionDep, name: str, current_user: CurrentSuperuser
) -> None:
    services.delete_role(session, services.get_role_or_404(session, name))


# --- global grants --------------------------------------------------------

@router.get(
    "/users/{username}/roles",
    response_model=list[str],
    summary="A user's global roles (superuser only)",
    dependencies=[Depends(require_permission(Permission.ROLE_READ))],
)
def list_user_roles(
    session: SessionDep, username: str, current_user: CurrentSuperuser
) -> list[str]:
    user = services.get_user_or_404(session, username)
    return global_role_names(session, user.id)


@router.post(
    "/users/{username}/roles",
    response_model=list[str],
    summary="Grant a global role (superuser only)",
    responses={400: {"description": "That role is project-scoped"}},
    dependencies=[Depends(require_permission(Permission.ROLE_MANAGE))],
)
def grant_user_role(
    session: SessionDep, username: str, body: GrantRoleRequest,
    current_user: CurrentSuperuser,
) -> list[str]:
    user = services.get_user_or_404(session, username)
    role = services.get_role_or_404(session, body.role)
    services.grant_global_role(session, user, role, granted_by=current_user.id)
    return global_role_names(session, user.id)


@router.delete(
    "/users/{username}/roles/{role_name}",
    response_model=list[str],
    summary="Revoke a global role (superuser only)",
    responses={409: {"description": "Would remove the last role manager"}},
    dependencies=[Depends(require_permission(Permission.ROLE_MANAGE))],
)
def revoke_user_role(
    session: SessionDep, username: str, role_name: str,
    current_user: CurrentSuperuser,
) -> list[str]:
    user = services.get_user_or_404(session, username)
    role = services.get_role_or_404(session, role_name)
    services.revoke_global_role(session, user, role,
                                acting_user_id=current_user.id)
    return global_role_names(session, user.id)


# --- user administration --------------------------------------------------
#
# Both of these are reads over other people's access, so they carry
# CurrentSuperuser alongside the role:read guard for the same reason the role
# endpoints above do: RBAC_MODE defaults to dry_run, where require_permission
# logs a refusal and then allows the request through. Until the mode reaches
# enforce, the superuser dependency is what actually keeps a roster of every
# account -- emails, status flags, who is an administrator -- from being readable
# by any authenticated caller. Dropping it is a Phase 5 change, not a cleanup.

@router.get(
    "/users",
    response_model=UsersAdminPublic,
    summary="The user roster (superuser only)",
    dependencies=[Depends(require_permission(Permission.ROLE_READ))],
)
def list_users(
    session: SessionDep,
    current_user: CurrentSuperuser,
    skip: int = Query(0, ge=0, description="Number of records to skip"),
    limit: int = Query(20, ge=1, le=100, description="Maximum records to return"),
    q: str | None = Query(
        None, description="Filter on username, email or full name"
    ),
    role: str | None = Query(
        None, description="Only users holding this global role"
    ),
    is_active: bool | None = Query(
        None, description="Filter on account status; omit for both"
    ),
    sort_by: Literal[
        "username", "email", "full_name", "created_at", "last_login"
    ] = Query("username"),
    sort_order: Literal["asc", "desc"] = Query("asc"),
) -> UsersAdminPublic:
    """
    Every local user account, with status flags and global roles.

    GET /users/search is the wrong endpoint for an administrator: it is the
    picker behind "grant a role to somebody", so it can answer from LDAP, it
    demands a query string, and it hides deactivated accounts -- which are
    exactly the accounts an administrator is looking for.

    `q` is an optional filter here rather than a required query, because the
    first thing this page has to do is show who exists.
    """
    return services.list_users(
        session, skip=skip, limit=limit, q=q, role=role, is_active=is_active,
        sort_by=sort_by, sort_order=sort_order,
    )


@router.get(
    "/users/{username}/access",
    response_model=UserAccessPublic,
    summary="One user's effective access (superuser only)",
    responses={404: {"description": "User not found"}},
    dependencies=[Depends(require_permission(Permission.ROLE_READ))],
)
def get_user_access(
    session: SessionDep, username: str, current_user: CurrentSuperuser
) -> UserAccessPublic:
    """
    Both grant planes and the break-glass flag for one user.

    The project memberships are the part that cannot be assembled from anything
    else: membership is otherwise only listable per project, so "which projects
    is this person on" has no answer without scanning every project.
    """
    user = services.get_user_or_404(session, username)
    return services.get_user_access(session, user)
