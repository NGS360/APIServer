"""
OAuth2 service for external authentication providers
"""
import logging
from datetime import datetime, timezone
import uuid

from fastapi import HTTPException, status
from sqlmodel import Session, select
import httpx

from api.auth.models import (
    User, OAuthProvider, OAuthProviderName
)
from core.config import get_settings
from core.security import generate_secure_token

logger = logging.getLogger(__name__)


class OAuth2ProviderConfig:
    """Configuration for OAuth2 providers"""

    PROVIDERS = {
        "google": {
            "authorize_url": "https://accounts.google.com/o/oauth2/v2/auth",
            "token_url": "https://oauth2.googleapis.com/token",
            "userinfo_url": "https://www.googleapis.com/oauth2/v2/userinfo",
            "scopes": ["openid", "email", "profile"],
        },
        "github": {
            "authorize_url": "https://github.com/login/oauth/authorize",
            "token_url": "https://github.com/login/oauth/access_token",
            "userinfo_url": "https://api.github.com/user",
            "scopes": ["user:email", "read:user"],
        },
        "microsoft": {
            "authorize_url": (
                "https://login.microsoftonline.com/common/oauth2/v2.0/"
                "authorize"
            ),
            "token_url": (
                "https://login.microsoftonline.com/common/oauth2/v2.0/"
                "token"
            ),
            "userinfo_url": "https://graph.microsoft.com/v1.0/me",
            "scopes": ["openid", "email", "profile"],
        },
    }

    @classmethod
    def get_provider_config(cls, provider: str) -> dict:
        """Get configuration for OAuth provider"""
        if provider not in cls.PROVIDERS:
            raise ValueError(f"Unsupported provider: {provider}")
        return cls.PROVIDERS[provider]


def get_available_providers() -> dict:
    """
    Get list of configured OAuth providers
    
    Returns which OAuth providers are configured and available for use.
    The client apps (e.g. React app) can use this to dynamically show login buttons.
    
    Returns:
        dict: Available providers with metadata
        
    Example Response:
        {
            "providers": [
                {
                    "name": "google",
                    "display_name": "Google",
                    "enabled": true,
                    "authorize_url": "/api/v1/auth/oauth/google/authorize"
                },
                {
                    "name": "github",
                    "display_name": "GitHub",
                    "enabled": true,
                    "authorize_url": "/api/v1/auth/oauth/github/authorize"
                }
            ]
        }
    """
    settings = get_settings()

    providers_info = []

    for provider in OAuth2ProviderConfig.PROVIDERS.keys():
        enabled = False
        if provider == "google":
            enabled = bool(settings.OAUTH_GOOGLE_CLIENT_ID and settings.OAUTH_GOOGLE_CLIENT_SECRET)
        elif provider == "github":
            enabled = bool(settings.OAUTH_GITHUB_CLIENT_ID and settings.OAUTH_GITHUB_CLIENT_SECRET)
        elif provider == "microsoft":
            enabled = bool(settings.OAUTH_MICROSOFT_CLIENT_ID and settings.OAUTH_MICROSOFT_CLIENT_SECRET)

        if enabled:
            providers_info.append({
                "name": provider,
                "display_name": provider.title(),
                "authorize_url": f"/api/v1/auth/oauth/{provider}/authorize" if enabled else None
            })

    if settings.OAUTH_CORP_NAME and settings.OAUTH_CORP_CLIENT_ID and settings.OAUTH_CORP_CLIENT_SECRET:
        providers_info.append({
            "name": settings.OAUTH_CORP_NAME.lower(),
            "display_name": settings.OAUTH_CORP_NAME,
            "authorize_url": f"/api/v1/auth/oauth/{settings.OAUTH_CORP_NAME.lower()}/authorize"
        })

    return {"count": len(providers_info), "providers": providers_info}


def get_authorization_url(
    provider: str,
    redirect_uri: str,
    state: str | None = None
) -> str:
    """
    Generate OAuth2 authorization URL

    Args:
        provider: OAuth provider name (google, github, microsoft)
        redirect_uri: Callback URL after authorization
        state: Optional state parameter for CSRF protection

    Returns:
        Authorization URL to redirect user to

    Raises:
        ValueError: If provider is not supported
        HTTPException: If provider credentials not configured
    """
    settings = get_settings()
    config = OAuth2ProviderConfig.get_provider_config(provider)

    # Get client ID based on provider
    client_id = None
    if provider == "google":
        client_id = settings.OAUTH_GOOGLE_CLIENT_ID
    elif provider == "github":
        client_id = settings.OAUTH_GITHUB_CLIENT_ID
    elif provider == "microsoft":
        client_id = settings.OAUTH_MICROSOFT_CLIENT_ID

    if not client_id:
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail=f"{provider.title()} OAuth not configured"
        )

    # Generate state if not provided
    if not state:
        state = generate_secure_token(16)

    # Build authorization URL
    scopes = " ".join(config["scopes"])
    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": scopes,
        "state": state,
    }

    # GitHub uses comma-separated scopes
    if provider == "github":
        params["scope"] = ",".join(config["scopes"])

    query_string = "&".join(f"{k}={v}" for k, v in params.items())
    return f"{config['authorize_url']}?{query_string}"


async def exchange_code_for_token(
    provider: str,
    code: str,
    redirect_uri: str
) -> dict:
    """
    Exchange authorization code for access token

    Args:
        provider: OAuth provider name
        code: Authorization code from callback
        redirect_uri: Callback URL (must match authorization request)

    Returns:
        Token response from provider

    Raises:
        HTTPException: If token exchange fails
    """
    settings = get_settings()
    config = OAuth2ProviderConfig.get_provider_config(provider)

    # Get client credentials
    client_id = None
    client_secret = None
    if provider == "google":
        client_id = settings.OAUTH_GOOGLE_CLIENT_ID
        client_secret = settings.OAUTH_GOOGLE_CLIENT_SECRET
    elif provider == "github":
        client_id = settings.OAUTH_GITHUB_CLIENT_ID
        client_secret = settings.OAUTH_GITHUB_CLIENT_SECRET
    elif provider == "microsoft":
        client_id = settings.OAUTH_MICROSOFT_CLIENT_ID
        client_secret = settings.OAUTH_MICROSOFT_CLIENT_SECRET

    if not client_id or not client_secret:
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail=f"{provider.title()} OAuth not configured"
        )

    # Exchange code for token
    data = {
        "client_id": client_id,
        "client_secret": client_secret,
        "code": code,
        "redirect_uri": redirect_uri,
        "grant_type": "authorization_code",
    }

    headers = {"Accept": "application/json"}

    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                config["token_url"],
                data=data,
                headers=headers
            )
            response.raise_for_status()
            return response.json()
    except httpx.HTTPError as e:
        logger.error(f"Token exchange failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Failed to exchange authorization code"
        )


async def get_user_info(provider: str, access_token: str) -> dict:
    """
    Get user information from OAuth provider

    Args:
        provider: OAuth provider name
        access_token: Access token from provider

    Returns:
        User information from provider

    Raises:
        HTTPException: If user info request fails
    """
    config = OAuth2ProviderConfig.get_provider_config(provider)

    headers = {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/json"
    }

    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(
                config["userinfo_url"],
                headers=headers
            )
            response.raise_for_status()
            user_data = response.json()

            # Normalize user data across providers
            return _normalize_user_data(provider, user_data)
    except httpx.HTTPError as e:
        logger.error(f"Failed to get user info: {e}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Failed to get user information"
        )


def _normalize_user_data(provider: str, data: dict) -> dict:
    """
    Normalize user data from different providers

    Args:
        provider: OAuth provider name
        data: Raw user data from provider

    Returns:
        Normalized user data with standard fields
    """
    if provider == "google":
        return {
            "provider_user_id": data.get("id"),
            "email": data.get("email"),
            "name": data.get("name"),
            "picture": data.get("picture"),
        }
    elif provider == "github":
        return {
            'provider_username': data.get("login"),
            "provider_user_id": str(data.get("id")),
            "email": data.get("email"),
            "name": data.get("name") or data.get("login"),
            "picture": data.get("avatar_url"),
        }
    elif provider == "microsoft":
        return {
            "provider_user_id": data.get("id"),
            "email": data.get("mail") or data.get("userPrincipalName"),
            "name": data.get("displayName"),
            "picture": None,
        }
    else:
        return data


def find_or_create_oauth_user(
    session: Session,
    provider: str,
    provider_data: dict,
    access_token: str,
    refresh_token: str | None = None
) -> User:
    """
    Find existing user or create new user from OAuth data

    Args:
        session: Database session
        provider: OAuth provider name
        provider_data: Normalized user data from provider
        access_token: OAuth access token
        refresh_token: OAuth refresh token (optional)

    Returns:
        User object (existing or newly created)

    Raises:
        HTTPException: If user creation fails
    """
    provider_user_id = provider_data.get("provider_user_id")
    email = provider_data.get("email")

    if not provider_user_id or not email:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid user data from OAuth provider"
        )

    # Check if OAuth provider link already exists
    statement = select(OAuthProvider).where(
        OAuthProvider.provider_name == provider,
        OAuthProvider.provider_user_id == provider_user_id
    )
    oauth_link = session.exec(statement).first()

    if oauth_link:
        # User already exists, update tokens
        oauth_link.access_token = access_token
        oauth_link.refresh_token = refresh_token
        oauth_link.updated_at = datetime.now(timezone.utc)
        session.add(oauth_link)
        session.commit()

        # Return existing user
        user = session.get(User, oauth_link.user_id)
        if not user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="User not found"
            )
        return user

    # Check if user with email already exists
    statement = select(User).where(User.email == email)
    user = session.exec(statement).first()

    if not user:
        # Create new user
        username = email.split("@")[0]
        # Ensure unique username
        base_username = username
        counter = 1
        while True:
            statement = select(User).where(User.username == username)
            if not session.exec(statement).first():
                break
            username = f"{base_username}{counter}"
            counter += 1

        user = User(
            user_id=User.generate_user_id(),
            email=email,
            username=username,
            full_name=provider_data.get("name"),
            hashed_password=None,  # OAuth-only user
            is_active=True,
            is_verified=True,  # Email verified by OAuth provider
        )
        session.add(user)
        session.commit()
        session.refresh(user)

    # Link OAuth provider to user
    oauth_provider = OAuthProvider(
        user_id=user.id,
        provider_name=OAuthProviderName(provider),
        provider_user_id=provider_user_id,
        access_token=access_token,
        refresh_token=refresh_token
    )
    session.add(oauth_provider)
    session.commit()

    return user


def link_oauth_account(
    session: Session,
    user_id: uuid.UUID,
    provider: str,
    provider_data: dict,
    access_token: str,
    refresh_token: str | None = None
) -> OAuthProvider:
    """
    Link OAuth provider to existing user account

    Args:
        session: Database session
        user_id: User ID to link to
        provider: OAuth provider name
        provider_data: Normalized user data from provider
        access_token: OAuth access token
        refresh_token: OAuth refresh token (optional)

    Returns:
        Created OAuthProvider link

    Raises:
        HTTPException: If link already exists or creation fails
    """
    provider_user_id = provider_data.get("provider_user_id")

    if not provider_user_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid user data from OAuth provider"
        )

    # Check if already linked
    statement = select(OAuthProvider).where(
        OAuthProvider.user_id == user_id,
        OAuthProvider.provider_name == provider
    )
    existing = session.exec(statement).first()

    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"{provider.title()} account already linked"
        )

    # Create link
    oauth_provider = OAuthProvider(
        user_id=user_id,
        provider_name=OAuthProviderName(provider),
        provider_user_id=provider_user_id,
        access_token=access_token,
        refresh_token=refresh_token
    )
    session.add(oauth_provider)
    session.commit()
    session.refresh(oauth_provider)

    return oauth_provider


def unlink_oauth_account(
    session: Session,
    user_id: uuid.UUID,
    provider: str
) -> bool:
    """
    Unlink OAuth provider from user account

    Args:
        session: Database session
        user_id: User ID
        provider: OAuth provider name

    Returns:
        True if unlinked successfully

    Raises:
        HTTPException: If cannot unlink (last auth method)
    """
    # Get user
    user = session.get(User, user_id)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )

    # Check if user has password
    has_password = user.hashed_password is not None

    # Count OAuth providers
    statement = select(OAuthProvider).where(
        OAuthProvider.user_id == user_id
    )
    oauth_count = len(session.exec(statement).all())

    # Prevent unlinking if it's the only auth method
    if not has_password and oauth_count <= 1:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot unlink last authentication method"
        )

    # Find and delete OAuth link
    statement = select(OAuthProvider).where(
        OAuthProvider.user_id == user_id,
        OAuthProvider.provider_name == provider
    )
    oauth_link = session.exec(statement).first()

    if not oauth_link:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"{provider.title()} account not linked"
        )

    session.delete(oauth_link)
    session.commit()

    return True
