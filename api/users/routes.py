"""
User search endpoints
"""
from fastapi import APIRouter, Depends, Query

from core.deps import SessionDep
from api.auth.deps import CurrentActiveUser
from api.rbac import services as rbac_services
from api.rbac.deps import require_permission
from api.rbac.models import UserAdminPublic, UserFlagsUpdate
from api.rbac.permissions import Permission
from api.rbac.resolver import global_role_names
from api.users.models import UserSearchResponse
from api.users import services

router = APIRouter(prefix="/users", tags=["Users"])


@router.get("/search", response_model=UserSearchResponse,
            dependencies=[Depends(require_permission(Permission.USER_READ))])
def search_users(
    session: SessionDep,
    current_user: CurrentActiveUser,
    q: str = Query(..., min_length=2, description="Search query (min 2 characters)"),
    limit: int = Query(20, ge=1, le=100, description="Max results to return"),
) -> UserSearchResponse:
    """
    Search for users by name, email, or username.

    Uses LDAP directory if configured and available,
    otherwise falls back to the local user database.

    Requires authentication.
    """
    return services.search_users(session, query=q, limit=limit)


@router.patch(
    "/{username}",
    response_model=UserAdminPublic,
    summary="Set a user's status flags",
    responses={
        404: {"description": "User not found"},
        409: {"description": "Would lock out the last superuser or role manager"},
    },
    dependencies=[Depends(require_permission(Permission.USER_MANAGE))],
)
def update_user_flags(
    session: SessionDep,
    username: str,
    body: UserFlagsUpdate,
    current_user: CurrentActiveUser,
) -> UserAdminPublic:
    """
    Activate, verify, or set the superuser flag. Omitted fields are unchanged.

    This is the route user:manage describes -- the permission has been in the
    catalog and in the admin role since RBAC landed, with nothing implementing
    it, so it granted nothing.

    is_active and is_verified are both required to authenticate, so clearing
    either one is an account lockout; the guardrails in api/rbac/services.py
    refuse the two lockouts that cannot be undone through the API, namely the
    last usable superuser and the last non-superuser role manager.

    user:manage is the only route guard, rather than that plus CurrentSuperuser,
    so the permission means what it says: an account holding it can deactivate a
    departed colleague without also being break-glass.

    Setting is_superuser is the exception, and it is checked in the service
    rather than here -- docs/RBAC.md asks for user:manage AND superuser on the
    break-glass flag, and that rule belongs to the mutation rather than to one
    way of reaching it. current_user is the acting user for those guardrails.
    """
    user = rbac_services.get_user_or_404(session, username)
    user = rbac_services.update_user_flags(
        session, user,
        acting_user=current_user,
        is_active=body.is_active,
        is_verified=body.is_verified,
        is_superuser=body.is_superuser,
    )
    return UserAdminPublic(
        username=user.username,
        email=user.email,
        full_name=user.full_name,
        is_active=user.is_active,
        is_verified=user.is_verified,
        is_superuser=user.is_superuser,
        created_at=user.created_at,
        last_login=user.last_login,
        global_roles=global_role_names(session, user.id),
    )
