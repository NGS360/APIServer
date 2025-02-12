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

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.app_context.pop()

    def test_get_projects(self):
        pass

    def test_create_project(self):
        pass

    def test_get_project(self):
        pass

    def test_update_project(self):
        pass

    def test_delete_project(self):
        pass
