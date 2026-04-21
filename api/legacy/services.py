"""
Services for legacy /api/v0/samples/search endpoints.

Translates legacy query patterns (from the Flask/ES app) to SQL queries
against the current Sample + SampleAttribute tables.
"""

from datetime import datetime
from sqlmodel import Session, select, func
from sqlalchemy.orm import selectinload

from api.samples.models import Sample, SampleAttribute
from api.legacy.models import (
    LegacySampleHit,
    LegacySampleSearchResponse,
    LegacySampleSearchPaginatedResponse,
)


# Top-level fields that map to Sample columns
FIELD_MAP = {
    "projectid": "project_id",
    "samplename": "sample_id",
}


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


def _build_query(
    filters: dict,
    tags: dict | None = None,
):
    """
    Build a SQLAlchemy select statement from legacy filter parameters.

    Args:
        filters: dict of top-level or attribute filters
            - Keys in FIELD_MAP are mapped to Sample columns
            - 'created_on' is handled as date prefix match
            - 'tags' key (if present) is extracted and handled separately
            - Other keys are treated as SampleAttribute key searches
        tags: Explicit tags dict (from POST body's filter_on.tags)

    Returns:
        A select statement for Sample objects
    """
    statement = select(Sample).options(selectinload(Sample.attributes))

    # Extract tags from filters if present
    if tags is None:
        tags = filters.pop("tags", None)
    else:
        filters.pop("tags", None)  # Remove if also present in filters

    # Handle top-level and attribute filters
    attr_filters = {}
    for key, value in filters.items():
        column_name = FIELD_MAP.get(key)
        if column_name:
            # Map to Sample column
            column = getattr(Sample, column_name)
            if isinstance(value, list):
                statement = statement.where(column.in_(value))
            else:
                statement = statement.where(column == value)
        elif key == "created_on":
            # Date prefix match on Sample.created_at
            # e.g., "2026-01-21" matches any timestamp on that date
            if isinstance(value, str) and Sample.created_at is not None:
                try:
                    date = datetime.strptime(value, "%Y-%m-%d").date()
                    statement = statement.where(
                        func.date(Sample.created_at) == date
                    )
                except ValueError:
                    pass  # Invalid date format, skip filter
        else:
            # Unknown key — treat as attribute filter
            attr_filters[key] = value

    # Handle attribute filters (from unknown keys)
    for attr_key, attr_value in attr_filters.items():
        # Case-insensitive key matching
        attr_subquery = (
            select(SampleAttribute.sample_id)
            .where(
                func.upper(SampleAttribute.key) == attr_key.upper(),
                SampleAttribute.value == attr_value,
            )
        )
        statement = statement.where(Sample.id.in_(attr_subquery))

    # Handle tags dict (from POST body)
    if tags and isinstance(tags, dict):
        for tag_key, tag_value in tags.items():
            attr_subquery = (
                select(SampleAttribute.sample_id)
                .where(
                    func.upper(SampleAttribute.key) == tag_key.upper(),
                    SampleAttribute.value == tag_value,
                )
            )
            statement = statement.where(Sample.id.in_(attr_subquery))

    return statement


def search_samples_get(
    session: Session,
    query_params: dict,
) -> LegacySampleSearchResponse:
    """
    Handle GET /api/v0/samples/search — no pagination, returns all matches.
    """
    # Make a mutable copy
    filters = dict(query_params)

    statement = _build_query(filters)
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
    # Separate tags before calling _build_query since it mutates filters.
    filters = {k: v for k, v in filter_on.items() if k != "tags"}
    tags = filter_on.get("tags")

    # Build query for total count (without pagination)
    count_filters = dict(filters)
    count_tags = dict(tags) if tags else None
    count_stmt = _build_query(count_filters, count_tags)
    all_results = session.exec(count_stmt).all()
    total = len(all_results)

    # Build query with pagination
    page_filters = dict(filters)
    page_tags = dict(tags) if tags else None
    statement = _build_query(page_filters, page_tags)
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
