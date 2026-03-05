"""
Routes/endpoints for the Platforms API
"""

from fastapi import APIRouter, status
from core.deps import SessionDep
from api.platforms.models import Platform, PlatformCreate, PlatformPublic
import api.platforms.services as services

router = APIRouter(prefix="/platforms", tags=["Platform Endpoints"])


@router.post(
    "",
    response_model=PlatformPublic,
    tags=["Platform Endpoints"],
    status_code=status.HTTP_201_CREATED,
)
def create_platform(session: SessionDep, platform_in: PlatformCreate) -> Platform:
    """Create a new platform."""
    return services.create_platform(session=session, platform_in=platform_in)


@router.get(
    "",
    response_model=list[PlatformPublic],
    tags=["Platform Endpoints"],
)
def get_platforms(session: SessionDep) -> list[PlatformPublic]:
    """Returns all registered platforms."""
    return services.get_platforms(session=session)


@router.get(
    "/{name}",
    response_model=PlatformPublic,
    tags=["Platform Endpoints"],
)
def get_platform_by_name(session: SessionDep, name: str) -> Platform:
    """Returns a single platform by name."""
    return services.get_platform_by_name(session=session, name=name)
