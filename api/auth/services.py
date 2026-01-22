"""
Authentication service layer for user management and authentication
"""
from datetime import datetime, timedelta, timezone
import uuid

from fastapi import HTTPException, status
from sqlmodel import Session, select

from api.auth.models import (
    User, UserRegister, RefreshToken, PasswordResetToken,
    EmailVerificationToken
)
from core.security import (
    hash_password, verify_password, create_access_token,
    create_refresh_token, generate_secure_token, validate_password_strength
)
from core.config import get_settings
from core.email import send_password_reset_email, send_verification_email


def authenticate_user(
    session: Session, email: str, password: str
) -> User | None:
    """
    Authenticate user with email and password

    Args:
        session: Database session
        email: User email
        password: Plain text password

    Returns:
        User object if authentication successful, None otherwise
    """
    # Find user by email
    statement = select(User).where(User.email == email)
    user = session.exec(statement).first()

    if not user:
        return None

    # Check if account is locked
    if user.locked_until and user.locked_until > datetime.now(timezone.utc):
        raise HTTPException(
            status_code=status.HTTP_423_LOCKED,
            detail=(
                "Account is temporarily locked due to "
                "too many failed login attempts"
            )
        )

    # Verify password
    if not user.hashed_password or not verify_password(
        password, user.hashed_password
    ):
        # Increment failed login attempts
        increment_failed_login(session, user)
        return None

    # Reset failed login attempts on successful login
    reset_failed_login(session, user)

    # Update last login
    update_last_login(session, user.id)

    return user


def register_user(session: Session, user_data: UserRegister) -> User:
    """
    Register a new user

    Args:
        session: Database session
        user_data: User registration data

    Returns:
        Created User object

    Raises:
        HTTPException: If email or username already exists
    """
    # Validate password strength
    is_valid, error_msg = validate_password_strength(user_data.password)
    if not is_valid:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=error_msg
        )

    # Check if email already exists
    statement = select(User).where(User.email == user_data.email)
    if session.exec(statement).first():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Email already registered"
        )

    # Check if username already exists
    statement = select(User).where(User.username == user_data.username)
    if session.exec(statement).first():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Username already taken"
        )

    # Create user
    user = User(
        user_id=User.generate_user_id(),
        email=user_data.email,
        username=user_data.username,
        hashed_password=hash_password(user_data.password),
        full_name=user_data.full_name,
        is_active=True,
        is_verified=False
    )

    session.add(user)
    session.commit()
    session.refresh(user)

    # Send verification email
    create_and_send_verification_email(session, user)

    return user


def refresh_access_token(session: Session, refresh_token_str: str) -> dict:
    """
    Refresh access token using refresh token

    Args:
        session: Database session
        refresh_token_str: Refresh token string

    Returns:
        Dictionary with new access_token and refresh_token

    Raises:
        HTTPException: If refresh token is invalid or expired
    """
    # Find refresh token
    statement = select(RefreshToken).where(
        RefreshToken.token == refresh_token_str,
        RefreshToken.revoked.is_(False)
    )
    refresh_token = session.exec(statement).first()

    if not refresh_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid refresh token"
        )

    # Check if expired
    if refresh_token.expires_at < datetime.now(timezone.utc):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Refresh token expired"
        )

    # Get user
    user = session.get(User, refresh_token.user_id)
    if not user or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found or inactive"
        )

    # Create new tokens
    access_token = create_access_token({"sub": str(user.id)})
    new_refresh_token = create_refresh_token(
        session,
        user.id,
        refresh_token.device_info
    )

    # Revoke old refresh token (token rotation)
    refresh_token.revoked = True
    refresh_token.revoked_at = datetime.now(timezone.utc)
    session.add(refresh_token)
    session.commit()

    settings = get_settings()
    return {
        "access_token": access_token,
        "refresh_token": new_refresh_token.token,
        "token_type": "bearer",
        "expires_in": settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60
    }


def revoke_refresh_token(session: Session, token_str: str) -> bool:
    """
    Revoke a refresh token (logout)

    Args:
        session: Database session
        token_str: Refresh token to revoke

    Returns:
        True if token was revoked
    """
    statement = select(RefreshToken).where(RefreshToken.token == token_str)
    token = session.exec(statement).first()

    if token and not token.revoked:
        token.revoked = True
        token.revoked_at = datetime.now(timezone.utc)
        session.add(token)
        session.commit()
        return True

    return False


def initiate_password_reset(session: Session, email: str) -> bool:
    """
    Initiate password reset process

    Args:
        session: Database session
        email: User email

    Returns:
        True (always, to prevent email enumeration)
    """
    # Find user
    statement = select(User).where(User.email == email)
    user = session.exec(statement).first()

    if user:
        # Generate reset token
        token_str = generate_secure_token()
        expires_at = datetime.now(timezone.utc) + timedelta(hours=1)

        reset_token = PasswordResetToken(
            user_id=user.id,
            token=token_str,
            expires_at=expires_at
        )

        session.add(reset_token)
        session.commit()

        # Send reset email
        send_password_reset_email(
            user.email, token_str, user.full_name or user.username
        )

    # Always return True to prevent email enumeration
    return True


def complete_password_reset(
    session: Session, token_str: str, new_password: str
) -> bool:
    """
    Complete password reset with token

    Args:
        session: Database session
        token_str: Reset token
        new_password: New password

    Returns:
        True if password was reset

    Raises:
        HTTPException: If token is invalid or expired
    """
    # Validate password strength
    is_valid, error_msg = validate_password_strength(new_password)
    if not is_valid:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=error_msg
        )

    # Find token
    statement = select(PasswordResetToken).where(
        PasswordResetToken.token == token_str,
        PasswordResetToken.used.is_(False)
    )
    reset_token = session.exec(statement).first()

    if not reset_token:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or already used reset token"
        )

    # Check if expired
    if reset_token.expires_at < datetime.now(timezone.utc):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Reset token has expired"
        )

    # Get user and update password
    user = session.get(User, reset_token.user_id)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )

    user.hashed_password = hash_password(new_password)
    user.updated_at = datetime.now(timezone.utc)

    # Mark token as used
    reset_token.used = True
    reset_token.used_at = datetime.now(timezone.utc)

    session.add(user)
    session.add(reset_token)
    session.commit()

    return True


def create_and_send_verification_email(session: Session, user: User) -> None:
    """
    Create verification token and send email

    Args:
        session: Database session
        user: User to send verification to
    """
    token_str = generate_secure_token()
    expires_at = datetime.now(timezone.utc) + timedelta(days=7)

    verification_token = EmailVerificationToken(
        user_id=user.id,
        token=token_str,
        expires_at=expires_at
    )

    session.add(verification_token)
    session.commit()

    send_verification_email(
        user.email, token_str, user.full_name or user.username
    )


def verify_email(session: Session, token_str: str) -> bool:
    """
    Verify user email with token

    Args:
        session: Database session
        token_str: Verification token

    Returns:
        True if email was verified

    Raises:
        HTTPException: If token is invalid or expired
    """
    statement = select(EmailVerificationToken).where(
        EmailVerificationToken.token == token_str,
        EmailVerificationToken.used.is_(False)
    )
    verification_token = session.exec(statement).first()

    if not verification_token:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or already used verification token"
        )

    if verification_token.expires_at < datetime.now(timezone.utc):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Verification token has expired"
        )

    user = session.get(User, verification_token.user_id)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )

    user.is_verified = True
    user.updated_at = datetime.now(timezone.utc)

    verification_token.used = True
    verification_token.used_at = datetime.now(timezone.utc)

    session.add(user)
    session.add(verification_token)
    session.commit()

    return True


def update_last_login(session: Session, user_id: uuid.UUID) -> None:
    """Update user's last login timestamp"""
    user = session.get(User, user_id)
    if user:
        user.last_login = datetime.now(timezone.utc)
        session.add(user)
        session.commit()


def increment_failed_login(session: Session, user: User) -> None:
    """Increment failed login attempts and lock account if needed"""
    settings = get_settings()
    user.failed_login_attempts += 1

    if user.failed_login_attempts >= settings.MAX_FAILED_LOGIN_ATTEMPTS:
        user.locked_until = datetime.now(timezone.utc) + timedelta(
            minutes=settings.ACCOUNT_LOCKOUT_DURATION_MINUTES
        )

    session.add(user)
    session.commit()


def reset_failed_login(session: Session, user: User) -> None:
    """Reset failed login attempts"""
    user.failed_login_attempts = 0
    user.locked_until = None
    session.add(user)
    session.commit()


def get_user_by_id(session: Session, user_id: uuid.UUID) -> User | None:
    """Get user by ID"""
    return session.get(User, user_id)


def get_user_by_email(session: Session, email: str) -> User | None:
    """Get user by email"""
    statement = select(User).where(User.email == email)
    return session.exec(statement).first()
