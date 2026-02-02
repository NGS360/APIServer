"""
Authentication dependencies for protecting endpoints
"""
from typing import Annotated
import uuid

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError

from core.deps import SessionDep
from core.security import decode_token
from api.auth.models import User
from api.auth.services import get_user_by_username

# OAuth2 scheme for token extraction
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login")

# Optional OAuth2 scheme (doesn't raise error if no token)
oauth2_scheme_optional = OAuth2PasswordBearer(
    tokenUrl="/api/v1/auth/login",
    auto_error=False
)


def get_current_user(
    session: SessionDep,
    token: Annotated[str, Depends(oauth2_scheme)]
) -> User:
    """
    Get current authenticated user from JWT token

    Args:
        session: Database session
        token: JWT access token

    Returns:
        Current User object

    Raises:
        HTTPException: If token is invalid or user not found
    """
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )

    try:
        payload = decode_token(token)
        username: str | None = payload.get("sub")
        if username is None:
            raise credentials_exception

    except (JWTError, ValueError):
        raise credentials_exception

    user = get_user_by_username(session, username)
    if user is None:
        raise credentials_exception

    return user


def get_current_active_user(
    current_user: Annotated[User, Depends(get_current_user)]
) -> User:
    """
    Get current active user (must be active and verified)

    Args:
        current_user: Current user from get_current_user

    Returns:
        Current User object

    Raises:
        HTTPException: If user is inactive or unverified
    """
    if not current_user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Inactive user"
        )

    if not current_user.is_verified:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Email not verified"
        )

    return current_user


def get_current_superuser(
    current_user: Annotated[User, Depends(get_current_active_user)]
) -> User:
    """
    Get current superuser (must be active, verified, and superuser)

    Args:
        current_user: Current user from get_current_active_user

    Returns:
        Current User object

    Raises:
        HTTPException: If user is not a superuser
    """
    if not current_user.is_superuser:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not enough permissions"
        )

    return current_user


def optional_current_user(
    session: SessionDep,
    token: Annotated[str | None, Depends(oauth2_scheme_optional)]
) -> User | None:
    """
    Get current user if token is provided, None otherwise

    Args:
        session: Database session
        token: Optional JWT access token

    Returns:
        Current User object or None
    """
    if token is None:
        return None

    try:
        payload = decode_token(token)
        username: str | None = payload.get("sub")
        if username is None:
            return None

        return get_user_by_username(session, username)
    except (JWTError, ValueError):
        return None


# Type aliases for cleaner endpoint signatures
CurrentUser = Annotated[User, Depends(get_current_user)]
CurrentActiveUser = Annotated[User, Depends(get_current_active_user)]
CurrentSuperuser = Annotated[User, Depends(get_current_superuser)]
OptionalUser = Annotated[User | None, Depends(optional_current_user)]
