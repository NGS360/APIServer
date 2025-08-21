"""
Routes/endpoints for the Search API
"""
from typing import Literal
from fastapi import APIRouter, Query

from core.deps import (
  OpenSearchDep
)
from api.search.models import (
  DynamicSearchResponse
)
import api.search.services as services

router = APIRouter(prefix="/search", tags=["Search Endpoints"])

@router.get(
  "",
  response_model=DynamicSearchResponse,
  tags=["Search Endpoints"]
)
def search(
  client: OpenSearchDep,
  index: str = Query(..., description="Index to search"),
  query: str = Query(..., description="Search query string"),
  page: int = Query(1, description="Page number (1-indexed)"),
  per_page: int = Query(20, description="Number of items per page"),
  sort_by: str | None = Query('name', description="Field to sort by (id, name)"),
  sort_order: Literal['asc', 'desc'] | None = Query('asc', description="Sort order (asc or desc)")
) -> DynamicSearchResponse:
  """
  Perform a search with pagination and sorting.
  """
  return services.search(
    client=client,
    index=index,
    query=query,
    page=page,
    per_page=per_page,
    sort_by=sort_by,
    sort_order=sort_order
  )
