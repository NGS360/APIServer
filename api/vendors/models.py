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

    model_config = ConfigDict(from_attributes=True)


class VendorsPublic(SQLModel):
    """
    Represents a paginated list of vendors
    """
    vendors: list[VendorPublic]
    total: int
    page: int
    per_page: int

    model_config = ConfigDict(from_attributes=True)
