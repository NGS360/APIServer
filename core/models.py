"""
Configure generic models not specific
to a particular feature.
"""

from sqlmodel import SQLModel


# Defined once, here, rather than per feature module. Projects, samples and
# workflows all need the same shape, and when each declared its own `Attribute`
# the three collided on schema name in the generated OpenAPI: FastAPI
# disambiguates by fully qualifying, so the spec carried
# `api__project__models__Attribute` and siblings. Which one kept the plain name
# depended on the order models happened to be registered, so adding an unrelated
# router could silently rename a type in every generated client. One definition
# means one `Attribute` schema and a stable name.
#
# Kept as a comment, not a docstring: a class docstring becomes the schema
# description and would ship to every API consumer.
class Attribute(SQLModel):
    """Reusable key-value pair for request/response payloads."""
    key: str | None
    value: str | None


class StatusResponse(SQLModel):
    status_code: int
    message: str | None


class HTTPErrorResponse(SQLModel):
    """Schema matching FastAPI's HTTPException response body."""
    detail: str
