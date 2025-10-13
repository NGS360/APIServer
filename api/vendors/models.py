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


class VendorCreate(SQLModel):
    """
    Represents the data needed to create a vendor
    """
    vendor_id: str
    name: str
    bucket: str | None = None


class VendorPublic(SQLModel):
    """
    Represents a public view of a vendor
    """
    vendor_id: str
    name: str
    bucket: str | None = None


class VendorUpdate(SQLModel):
    """
    Represents the data that can be updated for a vendor
    """
    name: str | None = None
    bucket: str | None = None


class VendorsPublic(SQLModel):
    """
    Represents a paginated list of vendors
    """
    data: list[VendorPublic]
    total_items: int
    total_pages: int
    current_page: int
    per_page: int
    has_next: bool
    has_prev: bool
