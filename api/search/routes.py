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
  query: str = Query(..., description="Search query string"),
  page: int = Query(1, description="Page number (1-indexed)"),
  per_page: int = Query(20, description="Number of items per page"),
) -> SearchPublic:
  """
  Perform a search with pagination and sorting.
  """
  return services.search(
    index="projects",  # Assuming the index is named 'projects'
    query=query,
    page=page,
    per_page=per_page
  )
