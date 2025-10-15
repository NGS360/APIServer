from sqlmodel import Session
from fastapi.testclient import TestClient

from api.project.models import Project
from api.samples.models import Sample
from api.project.services import generate_project_id

# from api.samples.models import Sample, SampleAttribute


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

    # Add a sample
    new_sample = Sample(sample_id="Sample_1", project_id=new_project_1.project_id)
    session.add(new_sample)
    new_sample = Sample(sample_id="Sample_2", project_id=new_project_1.project_id)
    session.add(new_sample)
    new_sample = Sample(sample_id="Sample_3", project_id=new_project_2.project_id)
    session.add(new_sample)
    session.commit()

    # Test with samples
    response = client.get(f"/api/v1/projects/{new_project_1.project_id}/samples")
    assert response.status_code == 200
    assert len(response.json()["data"]) == 2


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


def test_fail_to_add_sample_with_duplicate_attributes(
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
    assert "Extra inputs are not permitted" in response.json()["detail"][0]["msg"]


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
