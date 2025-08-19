"""
Routes/endpoints for the Search API
"""
from fastapi import APIRouter, Query

from core.deps import (
  OpenSearchDep
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
  client: OpenSearchDep,
  index: str = Query(..., description="Index to search"),
  query: str = Query(..., description="Search query string"),
  page: int = Query(1, description="Page number (1-indexed)"),
  per_page: int = Query(20, description="Number of items per page"),
) -> SearchPublic:
  """
  Perform a search with pagination and sorting.
  """
  return services.search(
    client=client,
    index=index,
    query=query,
    page=page,
    per_page=per_page
  )
