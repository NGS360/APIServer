'''
Test /api/projects endpoint
'''
import unittest

from config import TestConfig
from apiserver import create_app
from apiserver.extensions import DB as db
from apiserver.models import Project, ProjectAttribute

class TestProjects(unittest.TestCase):
    ''' Test cases for the projects API '''
    def setUp(self):
        self.app = create_app(TestConfig)
        self.app_context = self.app.app_context()
        self.app_context.push()
        db.create_all()
        # Test Client
        self.client = self.app.test_client()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.app_context.pop()

    def test_get_projects(self):
        ''' Test that we can get all projects '''
        # Test No projects
        response = self.client.get('/api/projects')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json, [])

        # Add a project
        new_project = Project(name="AI Research")
        new_project.project_id = Project.generate_project_id()
        new_project.attributes.append(
            ProjectAttribute(key="description", value="Exploring AI techniques")
        )
        new_project.attributes.append(ProjectAttribute(key="Department", value="R&D"))
        new_project.attributes.append(ProjectAttribute(key="Priority", value="High"))
        db.session.add(new_project)
        db.session.commit()

        # Test with projects
        response = self.client.get('/api/projects')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json), 1)
        self.assertEqual(response.json[0]['name'], 'AI Research')
        self.assertEqual(response.json[0]['attributes']['description'], 'Exploring AI techniques')
        self.assertEqual(response.json[0]['attributes']['Department'], 'R&D')
        self.assertEqual(response.json[0]['attributes']['Priority'], 'High')

    def test_create_project(self):
        ''' Test that we can add a project '''
        data = {
            'name': 'Test Project',
            'attributes': {
                'Department': 'R&D',
                'Priority': 'High'
            }
        }
        # Test
        response = self.client.post('/api/projects', json=data)
        # Check the response code
        self.assertEqual(response.status_code, 201)
        # Validate project details
        self.assertEqual(response.json['id'], 1)
        self.assertIn('project_id', response.json)
        self.assertEqual(response.json['name'], 'Test Project')
        # Validate attributes
        self.assertIn('attributes', response.json)
        self.assertEqual(response.json['attributes']['Department'], 'R&D')
        self.assertEqual(response.json['attributes']['Priority'], 'High')

        # Fetch from the database and validate
        project = db.session.get(Project, 1)
        self.assertIsNotNone(project)
        self.assertEqual(len(project.attributes), 2)
        self.assertEqual(project.attributes[0].key, 'Department')
        self.assertEqual(project.attributes[0].value, 'R&D')
        self.assertEqual(project.attributes[1].key, 'Priority')
        self.assertEqual(project.attributes[1].value, 'High')

    def test_get_project(self):
        ''' Test GET /api/projects/<project_id> works in different scenarios '''
        # Test when project not found and db is empty
        response = self.client.get('/api/projects/Test_Project')
        self.assertEqual(response.status_code, 404)

        # Add project to db
        new_project = Project(name="Test Project")
        project_id = Project.generate_project_id()
        new_project.project_id = project_id
        db.session.add(new_project)
        db.session.commit()

        # Test when project not found and db is not empty
        response = self.client.get('/api/projects/Test_Project')
        self.assertEqual(response.status_code, 404)
        response = self.client.get('/api/projects/test_project')
        self.assertEqual(response.status_code, 404)

        # Test when project is found
        response = self.client.get(f'/api/projects/{project_id}')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json['name'], 'Test Project')
        self.assertEqual(response.json['project_id'], project_id)

    def test_update_project(self):
        pass

    def test_delete_project(self):
        pass

if __name__ == '__main__':
    unittest.main()
