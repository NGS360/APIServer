"""
Legacy compatibility routes for /api/v0/samples/search.

These endpoints accept the same inputs as the old Flask app's
GET and POST /samples/search and return the old response format.
"""

from fastapi import APIRouter, Request
from core.deps import SessionDep
from api.legacy.models import (
    LegacySampleSearchResponse,
    LegacySampleSearchPaginatedResponse,
    LegacySampleSearchRequest,
)
import api.legacy.services as services

router = APIRouter(prefix="/samples", tags=["Legacy Endpoints"])


@router.get(
    "/search",
    response_model=LegacySampleSearchResponse,
)
def legacy_search_samples_get(
    request: Request,
    session: SessionDep,
) -> LegacySampleSearchResponse:
    """
    Search samples using query string parameters (legacy format).

    Accepts key/value pairs as query params, e.g.:
    ``?projectid=P-1234&samplename=Sample_1``

    Top-level fields: ``projectid``, ``samplename``, ``created_on``
    Any other key is matched against sample attributes (case-insensitive).

    Returns all matching samples (no pagination).
    """
    # Convert query params to dict, excluding internal FastAPI params
    query_params = {
        k: v for k, v in request.query_params.items()
        if k != "_"  # Legacy Flask clients may send _ for cache-busting
    }
    return services.search_samples_get(session=session, query_params=query_params)


@router.post(
    "/search",
    response_model=LegacySampleSearchPaginatedResponse,
)
def legacy_search_samples_post(
    session: SessionDep,
    body: LegacySampleSearchRequest,
) -> LegacySampleSearchPaginatedResponse:
    """
    Search samples using JSON body with filter_on, page, per_page (legacy format).

    Example body::

        {
            "filter_on": {
                "projectid": "P-1234",
                "tags": {
                    "USUBJID": "CA123012-01-234"
                }
            },
            "page": 1,
            "per_page": 100
        }

    ``filter_on`` supports:
    - ``projectid`` (str or list)
    - ``samplename`` (str or list)
    - ``created_on`` (str, date prefix match)
    - ``tags`` (dict of key/value pairs, matched case-insensitively)
    - Any other key is matched against sample attributes

    List values are OR'd; multiple keys are AND'd.
    """
    return services.search_samples_post(
        session=session,
        filter_on=body.filter_on,
        page=body.page,
        per_page=body.per_page,
    )
