"""
Routes/endpoints for the Vendors API

HTTP   URI                             Action
----   ---                             ------
GET    /api/v0/vendors                 Get list of vendors
POST   /api/v0/vendors                 Add a vendor run
GET    /api/v0/vendors/[id]            Retrieve info about a specific vendor
PUT    /api/v0/vendors/[id]            Update info about a vendor
"""

from typing import Literal
from fastapi import APIRouter, Query, status
from core.deps import SessionDep
from api.vendors.models import (
     Vendor,
     VendorCreate,
     VendorPublic,
     VendorsPublic,
)
from api.vendors import services

router = APIRouter(prefix="/vendors", tags=["Vendor Endpoints"])


@router.post(
    "",
    response_model=VendorPublic,
    tags=["Vendor Endpoints"],
    status_code=status.HTTP_201_CREATED,
)
def add_vendor(
    session: SessionDep,
    vendor_in: VendorCreate,
) -> Vendor:
    """
    Create a new vendor with optional attributes.
    """
    return services.add_vendor(
        session=session,
        vendor_in=vendor_in,
    )


@router.get(
    "",
    response_model=VendorsPublic,
    status_code=status.HTTP_200_OK,
    tags=["Vendor Endpoints"],
)
def get_vendors(
    session: SessionDep,
    page: int = Query(1, description="Page number (1-indexed)"),
    per_page: int = Query(20, description="Number of items per page"),
    sort_by: str = Query("id", description="Field to sort by"),
    sort_order: Literal["asc", "desc"] = Query(
        "asc", description="Sort order (asc or desc)"
    ),
):
    """
    Retrieve a list of all vendors.
    """
    return services.get_vendors(
        session=session,
        page=page,
        per_page=per_page,
        sort_by=sort_by,
        sort_order=sort_order,
    )


@router.get(
    "/{vendor_id}",
    response_model=VendorPublic,
    status_code=status.HTTP_200_OK,
    tags=["Vendor Endpoints"],
)
def get_vendor(session: SessionDep, vendor_id: str):
    """
    Retrieve a specific vendor by ID.
    """
    return services.get_vendor(session=session, vendor_id=vendor_id)


@router.put(
    "/{vendor_id}",
    response_model=VendorPublic,
    tags=["Vendor Endpoints"],
)
def update_vendor(
    session: SessionDep,
    update_request: VendorPublic
):
    """
    Update information about a specific vendor.
    """
    return services.update_vendor(
        session=session,
        update_request=update_request,
    )
