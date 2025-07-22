from main import app
from fastapi.testclient import TestClient

client = TestClient(app)


def test_get_samples_for_a_project():
    '''
    Test that we can get all samples for a project
    '''
    # Add a project to the database
    #new_project = Project(name="Test Project")
    #project_id = "P-1"
    #new_project.project_id = project_id
    #db.session.add(new_project)
    #db.session.commit()

    # Test No samples
    response = client.get('/api/projects/P-1/samples')
    assert response.status_code == 200
    assert response.json == []

    # Add a sample
    #new_sample = Sample(sample_id="Sample 1", project_id="P-1")
    #db.session.add(new_sample)
    #db.session.commit()

    # Test with samples
    response = client.get('/api/projects/P-1/samples')
    assert response.status_code == 200
    assert len(response.json) == 1
    assert response.json[0]['sample_id'] == 'Sample 1'

def test_create_sample():
    pass
