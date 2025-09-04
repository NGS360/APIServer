"""
Configure generic models not specific
to a particular feature.
"""

from sqlmodel import SQLModel
from fastapi import status


class StatusResponse(SQLModel):
    status_code: status
    message: str | None
