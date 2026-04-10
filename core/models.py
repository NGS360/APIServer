"""
Configure generic models not specific
to a particular feature.
"""

from sqlmodel import SQLModel


class StatusResponse(SQLModel):
    status_code: int
    message: str | None


class HTTPErrorResponse(SQLModel):
    """Schema matching FastAPI's HTTPException response body."""
    detail: str
