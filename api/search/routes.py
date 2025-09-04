"""
Routes/endpoints for the Search API
"""

from fastapi import APIRouter, Query

from core.deps import OpenSearchDep, SessionDep
from api.search.models import (
    SearchResponse,
)
import api.search.services as services

router = APIRouter(prefix="/search", tags=["Search Endpoints"])


@router.get("", response_model=SearchResponse, tags=["Search Endpoints"])
def search(
    client: OpenSearchDep,
    session: SessionDep,
    query: str = Query(..., description="Search query string"),
    n_results: int = Query(5, description="Number of results to return per index"),
) -> SearchResponse:
    return services.search(
        client=client, session=session, query=query, n_results=n_results
    )
