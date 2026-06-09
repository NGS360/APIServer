"""
User search service - orchestrates LDAP and database fallback.
"""
import logging

from sqlmodel import Session, select, or_, col

from api.auth.models import User
from api.users.models import UserSearchResult, UserSearchResponse
from api.users.ldap_service import search_users_ldap
from core.config import get_settings

logger = logging.getLogger(__name__)


def search_users_db(
    session: Session, query: str, limit: int = 20
) -> list[UserSearchResult]:
    """
    Search for users in the local database user table.

    Performs case-insensitive matching against username, email, and full_name.

    Args:
        session: Database session
        query: Search string
        limit: Maximum results to return

    Returns:
        List of UserSearchResult from the database.
    """
    search_term = f"%{query}%"
    statement = (
        select(User)
        .where(
            or_(
                col(User.username).ilike(search_term),
                col(User.email).ilike(search_term),
                col(User.full_name).ilike(search_term),
            )
        )
        .where(User.is_active == True)  # noqa: E712
        .limit(limit)
    )
    users = session.exec(statement).all()

    return [
        UserSearchResult(
            username=user.username,
            email=user.email,
            full_name=user.full_name,
            department=None,
            title=None,
            source="database",
        )
        for user in users
    ]


def search_users(
    session: Session, query: str, limit: int = 20
) -> UserSearchResponse:
    """
    Search for users. Tries LDAP first if configured, falls back to database.

    Args:
        session: Database session
        query: Search string (min 2 characters enforced at route level)
        limit: Maximum results to return

    Returns:
        UserSearchResponse with results and source indicator.
    """
    settings = get_settings()

    # Try LDAP first if enabled
    if settings.LDAP_ENABLED:
        ldap_results = search_users_ldap(query, limit)
        if ldap_results is not None:
            return UserSearchResponse(
                data=ldap_results,
                count=len(ldap_results),
                query=query,
                source="ldap",
            )
        logger.info(
            "LDAP unavailable, falling back to database for user search"
        )

    # Fallback to database
    db_results = search_users_db(session, query, limit)
    return UserSearchResponse(
        data=db_results,
        count=len(db_results),
        query=query,
        source="database",
    )
