"""
Authentication models for users, tokens, and OAuth providers
"""
from datetime import datetime, timezone
from enum import Enum
import uuid
from sqlmodel import Field, SQLModel
from pydantic import EmailStr, ConfigDict


class User(SQLModel, table=True):
    """User model with authentication support"""

    __tablename__ = "users"
    __searchable__ = ["email", "username", "full_name"]

    # Primary identifiers
    id: uuid.UUID | None = Field(default_factory=uuid.uuid4, primary_key=True)

    # Authentication
    email: str = Field(unique=True, index=True, max_length=255)
    username: str = Field(unique=True, index=True, max_length=50)
    hashed_password: str | None = Field(default=None, max_length=255)  # None for OAuth-only

    # Profile
    full_name: str | None = Field(default=None, max_length=255)

    # Status flags
    is_active: bool = Field(default=True)
    is_verified: bool = Field(default=False)
    is_superuser: bool = Field(default=False)

    # Timestamps
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    last_login: datetime | None = Field(default=None)

    # Security
    failed_login_attempts: int = Field(default=0)
    locked_until: datetime | None = Field(default=None)

    model_config = ConfigDict(from_attributes=True)


class RefreshToken(SQLModel, table=True):
    """Refresh token for maintaining user sessions"""

    __tablename__ = "refresh_tokens"

    id: uuid.UUID | None = Field(default_factory=uuid.uuid4, primary_key=True)
    username: str = Field(foreign_key="users.username", index=True)
    token: str = Field(unique=True, index=True, max_length=500)
    expires_at: datetime
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    revoked: bool = Field(default=False)
    revoked_at: datetime | None = Field(default=None)
    device_info: str | None = Field(default=None, max_length=500)

    model_config = ConfigDict(from_attributes=True)


class OAuthProviderName(str, Enum):
    """Supported OAuth providers"""
    GOOGLE = "google"
    GITHUB = "github"
    MICROSOFT = "microsoft"
    CORP = "corp"  # For internal corporate SSO

class OAuthProvider(SQLModel, table=True):
    """OAuth provider linkage for external authentication"""

    __tablename__ = "oauth_providers"

    id: uuid.UUID | None = Field(default_factory=uuid.uuid4, primary_key=True)
    user_id: uuid.UUID = Field(foreign_key="users.id", index=True)

    provider_name: str = Field(index=True, max_length=50)
    provider_user_id: str = Field(index=True, max_length=255)

    # OAuth tokens (should be encrypted in production)
    access_token: str | None = Field(default=None, max_length=1000)
    refresh_token: str | None = Field(default=None, max_length=1000)
    token_expires_at: datetime | None = Field(default=None)

    # Timestamps
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    model_config = ConfigDict(from_attributes=True)


class PasswordResetToken(SQLModel, table=True):
    """Password reset token for secure password recovery"""

    __tablename__ = "password_reset_tokens"

    id: uuid.UUID | None = Field(default_factory=uuid.uuid4, primary_key=True)
    username: str = Field(foreign_key="users.username", index=True)
    token: str = Field(unique=True, index=True, max_length=255)
    expires_at: datetime
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    used: bool = Field(default=False)
    used_at: datetime | None = Field(default=None)

    model_config = ConfigDict(from_attributes=True)


class EmailVerificationToken(SQLModel, table=True):
    """Email verification token for confirming user email addresses"""

    __tablename__ = "email_verification_tokens"

    id: uuid.UUID | None = Field(default_factory=uuid.uuid4, primary_key=True)
    username: str = Field(foreign_key="users.username", index=True)
    token: str = Field(unique=True, index=True, max_length=255)
    expires_at: datetime
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    used: bool = Field(default=False)
    used_at: datetime | None = Field(default=None)

    model_config = ConfigDict(from_attributes=True)


# Request/Response Models

class UserRegister(SQLModel):
    """User registration request"""
    email: EmailStr
    username: str = Field(min_length=3, max_length=50)
    password: str = Field(max_length=100)  # Validation done in service layer
    full_name: str | None = None


class UserLogin(SQLModel):
    """User login request"""
    email: EmailStr
    password: str


class TokenResponse(SQLModel):
    """Authentication token response"""
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int


class RefreshTokenRequest(SQLModel):
    """Refresh token request"""
    refresh_token: str


class PasswordResetRequest(SQLModel):
    """Password reset request"""
    email: EmailStr


class PasswordResetConfirm(SQLModel):
    """Password reset confirmation"""
    token: str
    new_password: str = Field(max_length=100)  # Validation in service layer


class PasswordChange(SQLModel):
    """Password change request"""
    current_password: str
    new_password: str = Field(max_length=100)  # Validation in service layer


class EmailVerificationRequest(SQLModel):
    """Email verification request"""
    token: str


class ResendVerificationRequest(SQLModel):
    """Resend verification email request"""
    email: EmailStr


class OAuthLinkRequest(SQLModel):
    """Link OAuth provider to account"""
    code: str


class UserPublic(SQLModel):
    """Public user information"""
    email: str
    username: str
    full_name: str | None
    is_active: bool
    is_verified: bool
    is_superuser: bool
    created_at: datetime
    last_login: datetime | None
    oauth_providers: list[str] = []


class UserUpdate(SQLModel):
    """User profile update"""
    full_name: str | None = None
    email: EmailStr | None = None
    username: str | None = None


class UsersPublic(SQLModel):
    """Paginated users response"""
    data: list[UserPublic]
    count: int
    page: int
    per_page: int


class OAuthProviderInfo(SQLModel):
    """OAuth provider information"""
    name: str
    display_name: str
    logo_url: str
    authorize_url: str


class AvailableProvidersResponse(SQLModel):
    """Available OAuth providers response"""
    count: int
    providers: list[OAuthProviderInfo]
