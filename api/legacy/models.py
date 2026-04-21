"""
Pydantic models for legacy /api/v0/samples/search endpoints.

These models produce the response shape expected by legacy clients
that have not migrated to the /api/v1 endpoints.
"""

from pydantic import BaseModel


class LegacySampleHit(BaseModel):
    """Single sample in legacy response format."""
    samplename: str
    projectid: str
    tags: dict[str, str] | None = None


class LegacySampleSearchResponse(BaseModel):
    """GET /api/v0/samples/search response (no pagination)."""
    total: int
    hits: list[LegacySampleHit]


class LegacySampleSearchPaginatedResponse(BaseModel):
    """POST /api/v0/samples/search response (with pagination)."""
    total: int
    page: int
    per_page: int
    hits: list[LegacySampleHit]


class LegacySampleSearchRequest(BaseModel):
    """POST /api/v0/samples/search request body."""
    filter_on: dict = {}
    page: int = 1
    per_page: int = 100
