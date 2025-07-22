'''
Test /projects endpoint
'''
from fastapi.testclient import TestClient
from sqlmodel import Session

from main import app
from api.project.models import Project, ProjectAttribute
from api.project.services import generate_project_id
from core.db import engine

client = TestClient(app)

# Create a test session
def get_test_session():
    with Session(engine) as session:
        yield session

def test_get_projects():
    ''' Test that we can get all projects '''
    # Test No projects
    response = client.get('/api/v1/projects')
    assert response.status_code == 200
    assert response.json() == {
        'data': [],
        'total_items': 0,
        'total_pages': 0,
        'current_page': 1,
        'per_page': 20,
        'has_next': False,
        'has_prev': False
    }

    # Get a session for testing
    session_generator = get_test_session()
    session = next(session_generator)
    try:
        # Add a project
        new_project = Project(name="AI Research")
        new_project.project_id = generate_project_id(session=session)
        
        # Initialize the attributes list if None
        if new_project.attributes is None:
            new_project.attributes = []
            
        new_project.attributes.append(
            ProjectAttribute(key="description", value="Exploring AI techniques")
        )
        new_project.attributes.append(ProjectAttribute(key="Department", value="R&D"))
        new_project.attributes.append(ProjectAttribute(key="Priority", value="High"))
        
        session.add(new_project)
        session.commit()  # Commit the changes
    
        # Test with projects
        response = client.get('/api/v1/projects')
        assert response.status_code == 200
        response_json = response.json()
        
        # Check the data structure
        assert 'data' in response_json
        assert len(response_json['data']) == 1
        
        # Verify project details
        project = response_json['data'][0]
        assert project['name'] == 'AI Research'
        
        # Check attributes (they're a list of objects with key/value pairs)
        attribute_dict = {attr['key']: attr['value'] for attr in project['attributes']}
        assert attribute_dict['description'] == 'Exploring AI techniques'
        assert attribute_dict['Department'] == 'R&D'
        assert attribute_dict['Priority'] == 'High'
    
    finally:
        # Clean up
        session.rollback()
        try:
            next(session_generator)  # Close the generator
        except StopIteration:
            pass

def test_create_project():
    ''' Test that we can add a project '''
    data = {
        'name': 'Test Project',
        'attributes': [
            {'key': 'Department', 'value': 'R&D'},
            {'key': 'Priority', 'value': 'High'}
        ]
    }
    # Test
    response = client.post('/api/v1/projects', json=data)
    # Check the response code
    assert response.status_code == 201
    json_response = response.json()
    # Validate project details
    assert 'project_id' in json_response
    assert json_response['name'] == 'Test Project'
    # Validate attributes
    assert 'attributes' in json_response
    assert json_response['attributes'][0]['key'] == 'Department'
    assert json_response['attributes'][0]['value'] == 'R&D'
    assert json_response['attributes'][1]['key'] == 'Priority'
    assert json_response['attributes'][1]['value'] == 'High'

def test_get_project():
    ''' Test GET /api/projects/<project_id> works in different scenarios '''
    # Test when project not found and db is empty
    response = client.get('/api/v1/projects/Test_Project')
    assert response.status_code == 404

    # Get a session for testing
    session_generator = get_test_session()
    session = next(session_generator)
    try:
        # Add project to db
        new_project = Project(name="Test Project")
        new_project.project_id = generate_project_id(session=session)
        new_project.attributes = []
        session.add(new_project)
        session.commit()

        # Test when project not found and db is not empty
        response = client.get('/api/v1/projects/Test_Project')
        assert response.status_code == 404
        response = client.get('/api/v1/projects/test_project')
        assert response.status_code == 404

        # Test when project is found
        response = client.get(f'/api/v1/projects/{new_project.project_id}')
        assert response.status_code == 200
        response_json = response.json()
        assert response_json['name'] == 'Test Project'
        assert response_json['project_id'] == new_project.project_id
    finally:
        # Clean up
        session.rollback()
        try:
            next(session_generator)  # Close the generator
        except StopIteration:
            pass

def test_update_project():
    pass

def test_delete_project():
    pass
