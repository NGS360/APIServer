from sqlmodel import Session
from fastapi.testclient import TestClient

from api.project.models import Project
from api.samples.models import Sample
from api.project.services import generate_project_id

#from api.samples.models import Sample, SampleAttribute


def test_get_samples_for_a_project_with_no_samples(client: TestClient, session: Session):
    '''
    Test that we can get all samples for a project
    '''
    # Add a project to the database
    new_project = Project(name="Test Project")
    new_project.project_id = generate_project_id(session=session)
    new_project.attributes = []
    session.add(new_project)
    session.commit()

    # Test No samples
    response = client.get(f'/api/v1/projects/{new_project.project_id}/samples')
    assert response.status_code == 200
    assert response.json() == {
        'current_page': 1,
        'data': [],
        'per_page': 20,
        'total_items': 0,
        'total_pages': 0,
        'has_next': False,
        'has_prev': False
    }


def test_get_samples_for_a_project_with_samples(client: TestClient, session: Session):
    '''
    Test that we can get all samples for a project with samples
    '''
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
    response = client.get(f'/api/v1/projects/{new_project_1.project_id}/samples')
    assert response.status_code == 200
    assert len(response.json()['data']) == 2
