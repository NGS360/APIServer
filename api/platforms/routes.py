"""
Routes/endpoints for the Platforms API
"""
from typing import Literal
from fastapi import APIRouter, Query, status
from core.deps import (
  SessionDep
)
from api.platforms.models import (
  Platform,
  PlatformCreate,
  PlatformPublic,
  PlatformsPublic
)
import api.platforms.services as services

router = APIRouter(prefix="/platforms", tags=["Platform Endpoints"])

@router.post(
  "",
  response_model=PlatformPublic,
  tags=["Platform Endpoints"],
  status_code=status.HTTP_201_CREATED
)
def create_platform(session: SessionDep, platform_in: PlatformCreate) -> Platform:
  """
  Create a new platform with optional attributes.
  """
  return services.create_platform(session=session, platform_in=platform_in)

@router.get(
  "",
  response_model=PlatformsPublic,
  tags=["Platform Endpoints"]
)
def get_platforms(
  session: SessionDep, 
  page: int = Query(1, description="Page number (1-indexed)"), 
  per_page: int = Query(20, description="Number of items per page"),
  sort_by: str = Query('platform_id', description="Field to sort by"),
  sort_order: Literal['asc', 'desc'] = Query('asc', description="Sort order (asc or desc)")
) -> PlatformsPublic:
  """
  Returns a paginated list of platforms.
  """
  return services.get_platforms(
    session=session, 
    page=page,
    per_page=per_page,
    sort_by=sort_by,
    sort_order=sort_order
  )

@router.get(
  "/{platform_id}",
  response_model=PlatformPublic,
  tags=["Platform Endpoints"]
)
def get_platform_by_platform_id(session: SessionDep, platform_id: str) -> Platform:
  """
  Returns a single platform by its platform_id.
  Note: This is different from its internal "id".
  """
  return services.get_platform_by_platform_id(
    session=session,
    platform_id=platform_id
  )