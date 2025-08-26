"""
Routes/endpoints for the Search API
"""
from typing import Literal
from fastapi import APIRouter, Query

from core.deps import (
  OpenSearchDep,
  SessionDep
)
from api.search.models import (
  SearchResponse,
  SearchResponseOriginal
)
import api.search.services as services

router = APIRouter(prefix="/search", tags=["Search Endpoints"])

@router.get(
  "_original",
  response_model=SearchResponseOriginal,
  tags=["Search Endpoints"]
)
def search_original(
  client: OpenSearchDep,
  session: SessionDep,
  index: str = Query(..., description="Index to search"),
  query: str = Query(..., description="Search query string"),
  page: int = Query(1, description="Page number (1-indexed)"),
  per_page: int = Query(20, description="Number of items per page"),
  sort_by: str | None = Query('name', description="Field to sort by (id, name)"),
  sort_order: Literal['asc', 'desc'] | None = Query('asc', description="Sort order (asc or desc)")
) -> SearchResponseOriginal:
  """
  Perform a search with pagination and sorting.
  """
  return services.search_original(
    client=client,
    index=index,
    query=query,
    page=page,
    per_page=per_page,
    sort_by=sort_by,
    sort_order=sort_order,
    session=session
  )

@router.get(
  "",
  response_model=SearchResponse,
  tags=["Search Endpoints"]
)
def search(
  client: OpenSearchDep,
  session: SessionDep,
  query: str = Query(..., description="Search query string"),
  n_results: int = Query(5, description="Number of results to return per index")
) -> SearchResponse:
  return services.search(
    client=client,
    session=session,
    query=query,
    n_results=n_results
  )