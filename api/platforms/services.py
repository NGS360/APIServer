"""
Services for managing platforms (workflow execution engines).
"""

from fastapi import HTTPException, status
from sqlmodel import Session, select
from sqlalchemy.exc import IntegrityError

from api.platforms.models import Platform, PlatformCreate, PlatformPublic


def create_platform(session: Session, platform_in: PlatformCreate) -> Platform:
    """Create a new platform."""
    platform = Platform(name=platform_in.name)

    try:
        session.add(platform)
        session.commit()
        session.refresh(platform)
    except IntegrityError as e:
        session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Platform '{platform_in.name}' already exists.",
        ) from e

    return platform


def get_platforms(session: Session) -> list[PlatformPublic]:
    """Return all platforms."""
    platforms = session.exec(select(Platform).order_by(Platform.name)).all()
    return [PlatformPublic(name=p.name) for p in platforms]


def get_platform_by_name(session: Session, name: str) -> Platform:
    """Get a single platform by name."""
    platform = session.get(Platform, name)
    if not platform:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Platform '{name}' not found.",
        )
    return platform
