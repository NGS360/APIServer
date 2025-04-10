import unittest

from config import TestConfig
from apiserver import create_app
from apiserver.extensions import DB as db
from apiserver.models import Project, Sample, SampleAttribute
class TestSamples(unittest.TestCase):
    ''' Test cases for the samples API '''
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

    def test_get_samples_for_a_project(self):
        '''
        Test that we can get all samples for a project
        '''
        # Add a project to the database
        new_project = Project(name="Test Project")
        project_id = "P-1"
        new_project.project_id = project_id
        db.session.add(new_project)
        db.session.commit()

        # Test No samples
        response = self.client.get('/api/projects/P-1/samples')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json, [])

        # Add a sample
        new_sample = Sample(sample_id="Sample 1", project_id="P-1")
        db.session.add(new_sample)
        db.session.commit()

        # Test with samples
        response = self.client.get('/api/projects/P-1/samples')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json), 1)
        self.assertEqual(response.json[0]['sample_id'], 'Sample 1')

    def test_create_sample(self):
        pass
