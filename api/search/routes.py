"""
Routes/endpoints for the Search API
"""
from typing import Literal
from fastapi import APIRouter, Query

from core.deps import (
  SessionDep
)
from api.search.models import (
  SearchPublic
)
import api.search.services as services

router = APIRouter(prefix="/search", tags=["Search Endpoints"])

@router.get(
  "",
  response_model=SearchPublic,
  tags=["Search Endpoints"]
)
def search(
  session: SessionDep,
  page: int = Query(1, description="Page number (1-indexed)"),
  per_page: int = Query(20, description="Number of items per page"),
  sort_by: str = Query('id', description="Field to sort by"),
  sort_order: Literal['asc', 'desc'] = Query('asc', description="Sort order (asc or desc)")
) -> SearchPublic:
  """
  Perform a search with pagination and sorting.
  """
  return services.search(
    session=session,
    page=page,
    per_page=per_page,
    sort_by=sort_by,
    sort_order=sort_order
  )
