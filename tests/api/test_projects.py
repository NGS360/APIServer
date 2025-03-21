'''
Test /api/projects endpoint
'''
import unittest

from config import TestConfig
from apiserver import create_app
from apiserver.extensions import DB as db

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
        response = self.client.get('/api/projects')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json, [])

    def test_create_project(self):
        ''' Test that we can add a project '''
        data = {
            'name': 'Test Project',
            'description': 'Test Description',
        }
        response = self.client.post('/api/projects', json=data)
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json['id'], 1)
        self.assertEqual(response.json['name'], 'Test Project')
        self.assertEqual(response.json['description'], 'Test Description')

    def test_get_project(self):
        pass

    def test_update_project(self):
        pass

    def test_delete_project(self):
        pass
