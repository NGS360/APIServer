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
from api.rbac.models import PermissionPublic, Role, RolePermission, RolePublic
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
