from sqlmodel import Session
from fastapi.testclient import TestClient

from api.project.models import Project
from api.project.services import generate_project_id

#from api.samples.models import Sample, SampleAttribute


def Xtest_get_samples_for_a_project(client: TestClient, session: Session):
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
    response = client.get('/api/v1/projects/P-1/samples')
    assert response.status_code == 200
    assert response.json() == []

    # Add a sample
    new_sample = Sample(sample_id="Sample 1", project_id="P-1")
    session.add(new_sample)
    session.commit()

    # Test with samples
    response = client.get('/api/v1/projects/P-1/samples')
    assert response.status_code == 200
    assert len(response.json) == 1
    assert response.json[0]['sample_id'] == 'Sample 1'
