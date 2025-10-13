from core.deps import SessionDep
from api.vendors.models import (
     Vendor,
     VendorCreate,
#     VendorPublic,
     VendorsPublic,
#     VendorUpdateRequest,
)


def add_vendor(session: SessionDep, vendor_in: VendorCreate) -> Vendor:
    """ Add a vendor """
    return Vendor()


def get_vendors(session: SessionDep, page: int, per_page: int, sort_by: str, sort_order: str) -> VendorsPublic:
    """ Get list of vendors """
    return VendorsPublic(
        vendors=[],
        total=0,
        page=page,
        per_page=per_page,
    )
