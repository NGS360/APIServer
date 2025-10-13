"""
Models for the Vendors API
"""

import uuid
from sqlmodel import SQLModel, Field
from pydantic import ConfigDict


class Vendor(SQLModel, table=True):
    """
    Represents a vendor
    """
    id: uuid.UUID | None = Field(default_factory=uuid.uuid4, primary_key=True)
    vendor_id: str = Field(index=True, unique=True)
    name: str = Field(max_length=100)
    bucket: str | None = Field(default=None, max_length=100)

    model_config = ConfigDict(from_attributes=True)
