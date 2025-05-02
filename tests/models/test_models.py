''' Test cases for the models module '''
import unittest
from unittest.mock import patch
from datetime import datetime
from pytz import timezone

from apiserver.models import Project

class TestModels(unittest.TestCase):
    ''' Test cases for the database model '''

    @patch('apiserver.models.datetime')
    @patch('apiserver.models.db.session.query')
    def test_generate_project_id(self, mock_query, mock_datetime):
        ''' Test the generate_project_id function '''
        # Mock the datetime to return a fixed date
        mock_now = datetime(2025, 5, 1, tzinfo=timezone('US/Eastern'))
        mock_datetime.now.return_value = mock_now
        
        # Case 1: No existing projects for today
        mock_query_instance = mock_query.return_value
        mock_filter = mock_query_instance.filter.return_value
        mock_order_by = mock_filter.order_by.return_value
        mock_order_by.first.return_value = None
        
        # Test the function
        project_id = Project.generate_project_id()
        
        # Verify the result
        self.assertEqual(project_id, "P-20250501-0001")
        mock_query.assert_called_once_with(Project)
        mock_query_instance.filter.assert_called_once()
        
        # Case 2: Existing projects for today
        mock_query.reset_mock()
        mock_existing_project = unittest.mock.MagicMock()
        mock_existing_project.project_id = "P-20250501-0042"
        mock_order_by.first.return_value = mock_existing_project
        
        # Test the function again
        project_id = Project.generate_project_id()
        
        # Verify the result
        self.assertEqual(project_id, "P-20250501-0043")
