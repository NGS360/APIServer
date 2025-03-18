'''
Test /api/projects endpoint
'''
import unittest

from config import TestConfig
from apiserver import create_app, db

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
        self.assertEqual(response.json,
            [
                { 'id': 1, 'name': 'test project'},
                { 'id': 2, 'name': 'test 2 project'},
                { 'id': 3, 'name': 'test 3 project'},
            ])

    def test_create_project(self):
        pass

    def test_get_project(self):
        pass

    def test_update_project(self):
        pass

    def test_delete_project(self):
        pass
