"""
Services for managing vendors
"""
from fastapi import HTTPException, status
from sqlmodel import select, func
from core.deps import SessionDep
from api.vendors.models import (
     Vendor,
     VendorCreate,
     VendorUpdate,
     VendorPublic,
     VendorsPublic,
)


def add_vendor(session: SessionDep, vendor_in: VendorCreate) -> VendorPublic:
    """ Add a vendor """
    # Create the Vendor instance
    vendor = Vendor(**vendor_in.model_dump())

    # Add to the database
    try:
        session.add(vendor)
        session.commit()
        session.refresh(vendor)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        ) from e
    # Return the created vendor
    return vendor


def get_vendors(
    session: SessionDep,
    page: int,
    per_page: int,
    sort_by: str,
    sort_order: str
) -> VendorsPublic:
    """ Get list of vendors """
    # Get total run count
    total_count = session.exec(select(func.count()).select_from(Vendor)).one()

    # Compute total pages
    total_pages = (total_count + per_page - 1) // per_page  # Ceiling division

    sort_field = getattr(Vendor, sort_by, Vendor.vendor_id)
    sort_direction = sort_field.asc() if sort_order == "asc" else sort_field.desc()

    # Get vendor selection
    vendors = session.exec(
        select(Vendor)
        .order_by(sort_direction)
        .limit(per_page)
        .offset((page - 1) * per_page)
    ).all()

    # Map to vendor
    vendors_public = [
        VendorPublic(**vendor.model_dump()) for vendor in vendors
    ]

    return VendorsPublic(
        data=vendors_public,
        total_items=total_count,
        total_pages=total_pages,
        current_page=page,
        per_page=per_page,
        has_next=page < total_pages,
        has_prev=page > 1,
    )


def get_vendor(session: SessionDep, vendor_id: str) -> VendorPublic:
    """ Get a specific vendor """
    vendor = session.exec(
        select(Vendor).where(Vendor.vendor_id == vendor_id)
    ).first()
    if not vendor:
        raise ValueError(f"Vendor with ID {vendor_id} not found")
    return VendorPublic(**vendor.model_dump())


def update_vendor(
    session: SessionDep,
    vendor_id: str,
    update_request: VendorUpdate
) -> VendorPublic:
    """ Update a specific vendor """
    vendor = session.exec(
        select(Vendor).where(Vendor.vendor_id == vendor_id)
    ).first()
    if not vendor:
        raise ValueError(f"Vendor with ID {vendor_id} not found")

    # Update only the fields that are provided (not None)
    for key, value in update_request.model_dump(exclude_unset=True).items():
        setattr(vendor, key, value)

    session.add(vendor)
    session.commit()
    session.refresh(vendor)

    return VendorPublic(**vendor.model_dump())
