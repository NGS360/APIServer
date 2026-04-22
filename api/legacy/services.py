"""
Services for legacy /api/v0/samples/search endpoints.

Translates legacy query patterns (from the Flask/ES app) to SQL queries
against the current Sample + SampleAttribute tables.
"""

from sqlmodel import Session

from api.samples.models import Sample
from api.samples.services import _build_sample_query
from api.legacy.models import (
    LegacySampleHit,
    LegacySampleSearchResponse,
    LegacySampleSearchPaginatedResponse,
)


def _sample_to_hit(sample: Sample) -> LegacySampleHit:
    """Convert a Sample ORM object to legacy response format."""
    tags = {}
    if sample.attributes:
        for attr in sample.attributes:
            tags[attr.key] = attr.value
    return LegacySampleHit(
        samplename=sample.sample_id,
        projectid=sample.project_id,
        tags=tags if tags else None,
    )


def search_samples_get(
    session: Session,
    query_params: dict,
) -> LegacySampleSearchResponse:
    """
    Handle GET /api/v0/samples/search — no pagination, returns all matches.
    """
    # Make a mutable copy
    filters = dict(query_params)

    statement = _build_sample_query(filters)
    samples = session.exec(statement).all()

    hits = [_sample_to_hit(s) for s in samples]
    return LegacySampleSearchResponse(total=len(hits), hits=hits)


def search_samples_post(
    session: Session,
    filter_on: dict,
    page: int = 1,
    per_page: int = 100,
) -> LegacySampleSearchPaginatedResponse:
    """
    Handle POST /api/v0/samples/search — with pagination.
    """
    # Make mutable copies to avoid modifying caller's dict.
    # Separate tags before calling _build_sample_query since it mutates filters.
    filters = {k: v for k, v in filter_on.items() if k != "tags"}
    tags = filter_on.get("tags")

    # Build query for total count (without pagination)
    count_filters = dict(filters)
    count_tags = dict(tags) if tags else None
    count_stmt = _build_sample_query(count_filters, count_tags)
    all_results = session.exec(count_stmt).all()
    total = len(all_results)

    # Build query with pagination
    page_filters = dict(filters)
    page_tags = dict(tags) if tags else None
    statement = _build_sample_query(page_filters, page_tags)
    offset = (page - 1) * per_page
    statement = statement.offset(offset).limit(per_page)
    samples = session.exec(statement).all()

    hits = [_sample_to_hit(s) for s in samples]
    return LegacySampleSearchPaginatedResponse(
        total=total,
        page=page,
        per_page=per_page,
        hits=hits,
    )
