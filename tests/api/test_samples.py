from sqlmodel import Session
from fastapi.testclient import TestClient

from api.project.models import Project
from api.samples.models import Sample, SampleAttribute
from api.project.services import generate_project_id


def test_get_samples_for_a_project_with_no_samples(
    client: TestClient, session: Session
):
    """
    Test that we can get all samples for a project
    """
    # Add a project to the database
    new_project = Project(name="Test Project")
    new_project.project_id = generate_project_id(session=session)
    new_project.attributes = []
    session.add(new_project)
    session.commit()

    # Test No samples
    response = client.get(f"/api/v1/projects/{new_project.project_id}/samples")
    assert response.status_code == 200
    assert response.json() == {
        "current_page": 1,
        "data": [],
        "data_cols": None,
        "per_page": 20,
        "total_items": 0,
        "total_pages": 0,
        "has_next": False,
        "has_prev": False,
    }


def test_get_samples_for_a_project_with_samples(client: TestClient, session: Session):
    """
    Test that we can get all samples for a project with samples
    """
    # Add a project to the database
    new_project_1 = Project(name="Test Project 1")
    new_project_1.project_id = generate_project_id(session=session)
    new_project_1.attributes = []
    session.add(new_project_1)

    # Add a second project
    new_project_2 = Project(name="Test Project 2")
    new_project_2.project_id = generate_project_id(session=session)
    new_project_2.attributes = []
    session.add(new_project_2)

    # Add sample 1
    sample_1 = Sample(sample_id="Sample_1", project_id=new_project_1.project_id)
    session.add(sample_1)
    session.flush()  # Flush to get the sample ID for attributes

    # Add attributes for Sample_1
    attr_1_1 = SampleAttribute(sample_id=sample_1.id, key="Tissue", value="Liver")
    attr_1_2 = SampleAttribute(sample_id=sample_1.id, key="Condition", value="Healthy")
    session.add(attr_1_1)
    session.add(attr_1_2)

    # Add sample 2
    sample_2 = Sample(sample_id="Sample_2", project_id=new_project_1.project_id)
    session.add(sample_2)
    session.flush()

    # Add attributes for Sample_2
    attr_2_1 = SampleAttribute(sample_id=sample_2.id, key="Tissue", value="Heart")
    attr_2_2 = SampleAttribute(sample_id=sample_2.id, key="Condition", value="Disease")
    session.add(attr_2_1)
    session.add(attr_2_2)

    # Add sample 3 to second project
    sample_3 = Sample(sample_id="Sample_3", project_id=new_project_2.project_id)
    session.add(sample_3)
    session.flush()

    # Add attributes for Sample_3
    attr_3_1 = SampleAttribute(sample_id=sample_3.id, key="Tissue", value="Brain")
    attr_3_2 = SampleAttribute(sample_id=sample_3.id, key="Condition", value="Healthy")
    session.add(attr_3_1)
    session.add(attr_3_2)

    session.commit()

    # Test with samples
    response = client.get(f"/api/v1/projects/{new_project_1.project_id}/samples")
    assert response.status_code == 200
    response_data = response.json()

    # Check that we have 2 samples
    assert len(response_data["data"]) == 2

    # Check that data_cols is present and contains the expected attribute keys
    assert "data_cols" in response_data
    assert response_data["data_cols"] is not None
    assert "Tissue" in response_data["data_cols"]
    assert "Condition" in response_data["data_cols"]

    # Check that attributes are present in the response for each sample
    for sample in response_data["data"]:
        assert "attributes" in sample
        assert sample["attributes"] is not None
        assert len(sample["attributes"]) == 2

        # Verify attribute structure
        attribute_keys = [attr["key"] for attr in sample["attributes"]]
        assert "Tissue" in attribute_keys
        assert "Condition" in attribute_keys

        # Verify specific sample attributes
        if sample["sample_id"] == "Sample_1":
            attrs = sample["attributes"]
            tissue_attr = next(attr for attr in attrs if attr["key"] == "Tissue")
            condition_attr = next(
                attr for attr in attrs if attr["key"] == "Condition"
            )
            assert tissue_attr["value"] == "Liver"
            assert condition_attr["value"] == "Healthy"
        elif sample["sample_id"] == "Sample_2":
            attrs = sample["attributes"]
            tissue_attr = next(attr for attr in attrs if attr["key"] == "Tissue")
            condition_attr = next(
                attr for attr in attrs if attr["key"] == "Condition"
            )
            assert tissue_attr["value"] == "Heart"
            assert condition_attr["value"] == "Disease"


def test_add_sample_to_project(client: TestClient, session: Session):
    """
    Test that we can add a sample to a project
    """
    # Add a project to the database
    new_project = Project(name="Test Project")
    new_project.project_id = generate_project_id(session=session)
    new_project.attributes = []
    session.add(new_project)
    session.commit()

    # Add a sample to the project
    sample_data = {
        "sample_id": "Sample_1",
        "attributes": [
            {"key": "Tissue", "value": "Liver"},
            {"key": "Condition", "value": "Healthy"},
        ],
    }

    response = client.post(
        f"/api/v1/projects/{new_project.project_id}/samples", json=sample_data
    )
    assert response.status_code == 201
    assert response.json()["sample_id"] == "Sample_1"


def test_fail_to_add__sample_with_duplicate_attributes(
    client: TestClient, session: Session
):
    """
    Test that we properly fail to add a sample with duplicate keys.
    """
    # Add a project to the database
    new_project = Project(name="Test Project")
    new_project.project_id = generate_project_id(session=session)
    new_project.attributes = []
    session.add(new_project)
    session.commit()

    # Add a sample to the project
    sample_data = {
        "sample_id": "Sample_1",
        "attributes": [
            {"key": "Tissue", "value": "Liver"},
            {"key": "Tissue", "value": "Heart"},
        ],
    }

    response = client.post(
        f"/api/v1/projects/{new_project.project_id}/samples", json=sample_data
    )
    assert response.status_code == 400


def test_fail_to_add_sample_to_project(client: TestClient, session: Session):
    """
    Test that we fail to add a sample to a project when a projecT_id is provided in sample data
    """
    # Add a project to the database
    new_project = Project(name="Test Project")
    new_project.project_id = generate_project_id(session=session)
    new_project.attributes = []
    session.add(new_project)
    session.commit()

    # Add a sample to the project
    sample_data = {
        "sample_id": "Sample_1",
        "project_id": "a_project_id",
        "attributes": [
            {"key": "Tissue", "value": "Liver"},
            {"key": "Condition", "value": "Healthy"},
        ],
    }

    response = client.post(
        f"/api/v1/projects/{new_project.project_id}/samples", json=sample_data
    )
    assert response.status_code == 422
    assert "Extra inputs are not permitted" in response.json()["errors"][0]["message"]


def test_fail_to_add_sample_to_nonexistent_project(
    client: TestClient, session: Session
):
    """
    Test that we cannot add a sample to a non-existent project
    """
    # Attempt to add a sample to a non-existent project
    sample_data = {
        "sample_id": "Sample_1",
        "attributes": [
            {"key": "Tissue", "value": "Liver"},
            {"key": "Condition", "value": "Healthy"},
        ],
    }

    response = client.post(
        "/api/v1/projects/non_existent_project/samples", json=sample_data
    )
    assert response.status_code == 404


def test_add_samples_with_same_sampleid_to_different_projects(
    client: TestClient, session: Session
):
    """
    Test that we can add samples with the same sample_id to different projects
    """
    # Add two projects to the database
    new_project_1 = Project(name="Test Project 1")
    new_project_1.project_id = generate_project_id(session=session)
    new_project_1.attributes = []
    session.add(new_project_1)

    new_project_2 = Project(name="Test Project 2")
    new_project_2.project_id = generate_project_id(session=session)
    new_project_2.attributes = []
    session.add(new_project_2)

    session.commit()

    # Add a sample to the first project
    sample_data = {
        "sample_id": "Sample_1",
        "attributes": [
            {"key": "Tissue", "value": "Liver"},
            {"key": "Condition", "value": "Healthy"},
        ],
    }

    response = client.post(
        f"/api/v1/projects/{new_project_1.project_id}/samples", json=sample_data
    )
    assert response.status_code == 201
    assert response.json()["sample_id"] == "Sample_1"

    # Add a sample with the same sample_id to the second project
    sample_data = {
        "sample_id": "Sample_1",
        "attributes": [
            {"key": "Tissue", "value": "Breast"},
            {"key": "Condition", "value": "Healthy"},
        ],
    }
    response = client.post(
        f"/api/v1/projects/{new_project_2.project_id}/samples", json=sample_data
    )
    assert response.status_code == 201
    assert response.json()["sample_id"] == "Sample_1"


def test_update_sample_attribute(client: TestClient, session: Session):
    """
    Test that we can update a sample attribute
    """
    # Add a project to the database
    new_project = Project(name="Test Project")
    new_project.project_id = generate_project_id(session=session)
    new_project.attributes = []
    session.add(new_project)
    session.commit()

    # Add a sample to the project
    sample_data = {
        "sample_id": "Sample_1",
        "attributes": [
            {"key": "Tissue", "value": "Liver"},
            {"key": "Condition", "value": "Healthy"},
        ],
    }

    response = client.post(
        f"/api/v1/projects/{new_project.project_id}/samples", json=sample_data
    )
    assert response.status_code == 201
    assert response.json()["sample_id"] == "Sample_1"

    # Update an attribute
    update_data = {"key": "Condition", "value": "Diseased"}
    response = client.put(
        f"/api/v1/projects/{new_project.project_id}/samples/Sample_1",
        json=update_data,
    )
    assert response.status_code == 200
    assert any(
        attr["key"] == "Condition" and attr["value"] == "Diseased"
        for attr in response.json()["attributes"]
    )
