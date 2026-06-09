"""
Routes/endpoints for the Samples API
"""

from fastapi import APIRouter, Request, Query, status
from core.deps import SessionDep, OpenSearchDep
from api.samples.models import SamplesPublicSearchResponse, SampleSearchRequest
import api.samples.services as services

router = APIRouter(prefix="/samples", tags=["Sample Endpoints"])


# ---------------------------------------------------------------------------
# Search endpoints
# ---------------------------------------------------------------------------


@router.get(
    "/search",
    response_model=SamplesPublicSearchResponse,
    status_code=status.HTTP_200_OK,
    tags=["Sample Endpoints"],
)
def search_samples_get(
    request: Request,
    session: SessionDep,
    page: int = Query(1, description="Page number (1-indexed)"),
    per_page: int = Query(20, description="Number of items per page"),
) -> SamplesPublicSearchResponse:
    """
    Search samples using query string parameters.

    Accepts key/value pairs as query params, e.g.:
    ``?projectid=P-1234&samplename=Sample_1&page=1&per_page=20``

    Supported filter keys:
    - ``projectid``: exact match on project ID
    - ``samplename``: exact match on sample name
    - ``created_at``: date prefix match (YYYY-MM-DD) on created_at
    - Any other key: matched against sample attributes (case-insensitive key)

    Multiple filters are AND'd together.
    """
    # Convert query params to dict, excluding pagination and cache-busting
    excluded = {"page", "per_page", "_"}
    query_params = {
        k: v for k, v in request.query_params.items()
        if k not in excluded
    }
    return services.search_samples(
        session=session,
        filters=query_params,
        page=page,
        per_page=per_page,
    )


@router.post(
    "/search",
    response_model=SamplesPublicSearchResponse,
    status_code=status.HTTP_200_OK,
    tags=["Sample Endpoints"],
)
def search_samples_post(
    session: SessionDep,
    body: SampleSearchRequest,
) -> SamplesPublicSearchResponse:
    """
    Search samples using JSON body with filter_on, page, per_page.

    Example body::

        {
            "filter_on": {
                "projectid": "P-1234",
                "tags": {
                    "USUBJID": "CA123012-01-234"
                }
            },
            "page": 1,
            "per_page": 20
        }

    ``filter_on`` supports:
    - ``projectid`` (str or list)
    - ``samplename`` (str or list)
    - ``created_at`` (str, date prefix match)
    - ``tags`` (dict of key/value pairs, matched case-insensitively)
    - Any other key is matched against sample attributes

    List values are OR'd; multiple keys are AND'd.
    """
    # Separate tags before passing to service (since _build_sample_query
    # mutates filters dict)
    filters = {k: v for k, v in body.filter_on.items() if k != "tags"}
    tags = body.filter_on.get("tags")

    return services.search_samples(
        session=session,
        filters=filters,
        tags=tags,
        page=body.page,
        per_page=body.per_page,
    )


# ---------------------------------------------------------------------------
# Reindex endpoint
# ---------------------------------------------------------------------------


@router.post(
    "/reindex",
    status_code=status.HTTP_201_CREATED,
    tags=["Sample Endpoints"],
)
def reindex_samples(
    session: SessionDep,
    client: OpenSearchDep,
):
    """
    Reindex samples in database with OpenSearch
    """
    services.reindex_samples(session, client)
    return 'OK'
