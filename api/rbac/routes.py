"""
Read endpoints for roles and permissions.

Guarded by CurrentSuperuser rather than require_permission(ROLE_READ), and that
is deliberate for now: nothing enforces permissions yet, and gating the role API
on a role permission is a chicken-and-egg -- you would need a grant to make the
first grant. They move onto require_permission in phase 4 alongside every other
route.

Mutations (create/edit roles, grant and revoke) are not here yet.
"""

from fastapi import APIRouter, HTTPException, status
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
)
from api.rbac.permissions import CATALOG
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
)
def list_roles(session: SessionDep, current_user: CurrentSuperuser) -> list[RolePublic]:
    roles = session.exec(select(Role).order_by(Role.scope, Role.name)).all()
    return [_role_public(session, role) for role in roles]


@router.get(
    "/roles/{name}",
    response_model=RolePublic,
    summary="Get one role (superuser only)",
    responses={404: {"description": "Role not found"}},
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
