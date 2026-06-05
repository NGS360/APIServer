"""
User search endpoints
"""
from fastapi import APIRouter, Query

from core.deps import SessionDep
from api.auth.deps import CurrentActiveUser
from api.users.models import UserSearchResponse
from api.users import services

router = APIRouter(prefix="/users", tags=["Users"])


@router.get("/search", response_model=UserSearchResponse)
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
