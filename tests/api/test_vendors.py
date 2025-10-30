""" Test cases for vendor-related API endpoints """
from api.vendors.models import VendorCreate


def test_add_vendor(client):
    """ Test adding a vendor """
    new_vendor = VendorCreate(
        vendor_id="vendor_a",
        name="Vendor A",
        description="Description for Vendor A",
        bucket="s3://vendor-a-bucket"
    )

    response = client.post(
        "/api/v1/vendors",
        json=new_vendor.model_dump(),
    )
    assert response.status_code == 201
    data = response.json()
    assert data["vendor_id"] == new_vendor.vendor_id
    assert data["name"] == new_vendor.name
    assert data["bucket"] == new_vendor.bucket
    assert "id" not in data  # Ensure internal ID is not exposed

    # Test adding the same vendor_id again should fail
    new_vendor = VendorCreate(
        vendor_id="vendor_a",
        name="Vendor B",
        description="Description for Vendor B",
        bucket="s3://vendor-b-bucket"
    )
    response = client.post(
        "/api/v1/vendors",
        json=new_vendor.model_dump(),
    )
    assert response.status_code == 409


def test_get_vendors(client):
    """ Test retrieving vendors """
    # First, add a vendor to ensure there's at least one in the database
    new_vendor = VendorCreate(
        vendor_id="vendor_b",
        name="Vendor B",
        description="Description for Vendor B",
        bucket="s3://vendor-b-bucket"
    )
    client.post("/api/v1/vendors", json=new_vendor.model_dump())

    # Now, retrieve the list of vendors
    response = client.get("/api/v1/vendors")
    assert response.status_code == 200
    data = response.json()

    assert "data" in data
    assert isinstance(data["data"], list)
    assert len(data["data"]) >= 1  # At least one vendor should be present

    # Check that the added vendor is in the list
    vendor_ids = [vendor["vendor_id"] for vendor in data["data"]]
    assert new_vendor.vendor_id in vendor_ids


def test_get_vendor(client):
    """ Test retrieving a specific vendor """
    # First, add a vendor to ensure it exists in the database
    new_vendor = VendorCreate(
        vendor_id="vendor_c",
        name="Vendor C",
        description="Description for Vendor C",
        bucket="s3://vendor-c-bucket"
    )
    post_response = client.post("/api/v1/vendors", json=new_vendor.model_dump())
    assert post_response.status_code == 201
    created_vendor = post_response.json()

    # Now, retrieve the specific vendor by vendor_id
    response = client.get(f"/api/v1/vendors/{created_vendor['vendor_id']}")
    assert response.status_code == 200
    data = response.json()

    assert data["vendor_id"] == new_vendor.vendor_id
    assert data["name"] == new_vendor.name
    assert data["bucket"] == new_vendor.bucket
    assert "id" not in data  # Ensure internal ID is not exposed


def test_update_vendor(client):
    """ Test updating a vendor """
    # First, add a vendor to ensure it exists in the database
    new_vendor = VendorCreate(
        vendor_id="vendor_d",
        name="Vendor D",
        description="Description for Vendor D",
        bucket="s3://vendor-d-bucket"
    )
    post_response = client.post("/api/v1/vendors", json=new_vendor.model_dump())
    assert post_response.status_code == 201
    created_vendor = post_response.json()

    # Now, update the vendor's name and bucket
    update_data = {
        "name": "Vendor D Updated",
        "bucket": "s3://vendor-d-updated-bucket"
    }
    response = client.put(f"/api/v1/vendors/{created_vendor['vendor_id']}", json=update_data)
    assert response.status_code == 200
    data = response.json()

    assert data["vendor_id"] == new_vendor.vendor_id
    assert data["name"] == update_data["name"]
    assert data["bucket"] == update_data["bucket"]
    assert "id" not in data  # Ensure internal ID is not exposed
