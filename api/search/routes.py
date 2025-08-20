"""
Routes/endpoints for the Search API
"""
from typing import List, Literal
from fastapi import APIRouter, Query, HTTPException

from core.deps import OpenSearchDep
from core.opensearch import INDEXES
from api.search.models import MultiSearchPublic
import api.search.services as services

router = APIRouter(prefix="/search", tags=["Search Endpoints"])

@router.get(
    "",
    response_model=MultiSearchPublic,
    tags=["Search Endpoints"]
)
async def search(
    client: OpenSearchDep,
    indexes: List[str] = Query(..., description=f"Indexes to search. Available: {INDEXES}"),
    query: str = Query(..., description="Search query string"),
    page: int = Query(1, ge=1, description="Page number (1-indexed)"),
    per_page: int = Query(20, ge=1, le=100, description="Number of items per page (max 100)"),
    sort_by: str | None = Query('name', description="Field to sort by (id, name)"),
    sort_order: Literal['asc', 'desc'] | None = Query('asc', description="Sort order (asc or desc)")
) -> MultiSearchPublic:
    """
    Search across multiple OpenSearch indexes with individual pagination per index.
    
    This endpoint searches multiple indexes in parallel and returns separate result sets
    for each index with individual pagination controls.
    
    **Features:**
    - **Parallel execution**: All indexes are searched simultaneously for optimal performance
    - **Individual pagination**: Each index maintains its own pagination state
    - **Error resilience**: Partial failures don't break the entire response
    - **Flexible querying**: Same query applied across all specified indexes
    
    **Example Usage:**
    - Single index: `?indexes=projects&query=test`
    - Multiple indexes: `?indexes=projects&indexes=samples&query=test`
    - All indexes: `?indexes=projects&indexes=samples&indexes=illumina_runs&query=test`
    
    **Response Structure:**
    ```json
    {
      "results": {
        "projects": {
          "items": [...],
          "total": 150,
          "page": 1,
          "per_page": 20,
          "has_next": true,
          "success": true
        },
        "samples": {
          "items": [...],
          "total": 25,
          "page": 1,
          "per_page": 20,
          "has_next": false,
          "success": true
        }
      },
      "query": "test",
      "total_across_indexes": 175,
      "partial_failure": false
    }
    ```
    """
    if not indexes:
        raise HTTPException(status_code=400, detail="At least one index must be specified")
    
    # Validate that all requested indexes are valid
    invalid_indexes = [idx for idx in indexes if idx not in INDEXES]
    if invalid_indexes:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid indexes: {invalid_indexes}. Valid indexes are: {INDEXES}"
        )
    
    return await services.multi_search(
        client=client,
        indexes=indexes,
        query=query,
        page=page,
        per_page=per_page,
        sort_by=sort_by,
        sort_order=sort_order
    )
