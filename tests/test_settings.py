"""
Tests for core.config module including Settings and get_secret function
"""
import json
import pytest
from unittest.mock import Mock, patch
from botocore.exceptions import ClientError
from core.config import get_secret, get_settings


class TestGetSecret:
    """Test suite for get_secret function"""

    @patch('core.config.boto3.session.Session')
    def test_get_secret_success(self, mock_session_class):
        """Test successful secret retrieval from AWS Secrets Manager"""
        # Arrange: Set up the mock chain
        # Mock the secrets manager client
        mock_client = Mock()
        mock_client.get_secret_value.return_value = {
            'SecretString': json.dumps({
                'database_url': 'postgresql://user:pass@localhost/db',
                'api_key': 'test-api-key-123'
            })
        }

        # Mock the session to return our mock client
        mock_session = Mock()
        mock_session.client.return_value = mock_client

        # Mock the Session class to return our mock session
        mock_session_class.return_value = mock_session

        # Act: Call get_secret
        result = get_secret('my-secret', 'us-east-1')

        # Assert: Verify the result and mock calls
        assert result == {
            'database_url': 'postgresql://user:pass@localhost/db',
            'api_key': 'test-api-key-123'
        }

        # Verify Session was instantiated
        mock_session_class.assert_called_once()

        # Verify client was created with correct parameters
        mock_session.client.assert_called_once_with(
            service_name='secretsmanager',
            region_name='us-east-1'
        )

        # Verify get_secret_value was called with correct secret name
        mock_client.get_secret_value.assert_called_once_with(
            SecretId='my-secret'
        )

    @patch('core.config.boto3.session.Session')
    def test_get_secret_with_newlines(self, mock_session_class):
        """Test that newlines in secret strings are properly handled"""
        # Arrange: Create a secret with newlines
        mock_client = Mock()
        mock_client.get_secret_value.return_value = {
            'SecretString': '{\n"key1": "value1",\n"key2": "value2"\n}'
        }

        mock_session = Mock()
        mock_session.client.return_value = mock_client
        mock_session_class.return_value = mock_session

        # Act
        result = get_secret('my-secret', 'us-west-2')

        # Assert: Newlines should be stripped and JSON parsed correctly
        assert result == {'key1': 'value1', 'key2': 'value2'}

    @patch('core.config.boto3.session.Session')
    def test_get_secret_client_error(self, mock_session_class):
        """Test that ClientError is properly raised when secret retrieval fails"""
        # Arrange: Set up mock to raise ClientError
        mock_client = Mock()
        mock_client.get_secret_value.side_effect = ClientError(
            error_response={
                'Error': {
                    'Code': 'ResourceNotFoundException',
                    'Message': 'Secret not found'
                }
            },
            operation_name='GetSecretValue'
        )

        mock_session = Mock()
        mock_session.client.return_value = mock_client
        mock_session_class.return_value = mock_session

        # Act & Assert: Verify ClientError is raised
        with pytest.raises(ClientError) as exc_info:
            get_secret('non-existent-secret', 'us-east-1')

        # Verify error details
        assert exc_info.value.response['Error']['Code'] == 'ResourceNotFoundException'

    @patch('core.config.boto3.session.Session')
    def test_get_secret_different_regions(self, mock_session_class):
        """Test that get_secret works with different AWS regions"""
        # Arrange
        mock_client = Mock()
        mock_client.get_secret_value.return_value = {
            'SecretString': '{"region_test": "passed"}'
        }

        mock_session = Mock()
        mock_session.client.return_value = mock_client
        mock_session_class.return_value = mock_session

        # Act: Test with different region
        result = get_secret('my-secret', 'eu-west-1')

        # Assert: Verify correct region was used
        mock_session.client.assert_called_once_with(
            service_name='secretsmanager',
            region_name='eu-west-1'
        )
        assert result == {'region_test': 'passed'}


class TestSettings:
    """Test suite for Settings class"""

    def test_settings_with_env_vars(self, monkeypatch):
        """Test Settings uses environment variables when available"""
        # Arrange: Set environment variables
        monkeypatch.setenv('SQLALCHEMY_DATABASE_URI', 'postgresql://test:test@localhost/testdb')
        monkeypatch.setenv('OPENSEARCH_HOST', 'localhost')
        monkeypatch.setenv('OPENSEARCH_PORT', '9200')
        monkeypatch.setenv('OPENSEARCH_USER', 'admin')
        monkeypatch.setenv('OPENSEARCH_PASSWORD', 'admin123')

        # Clear the lru_cache to get fresh settings
        get_settings.cache_clear()

        # Act: Get settings
        settings = get_settings()

        # Assert: Verify values come from environment
        assert settings.SQLALCHEMY_DATABASE_URI == 'postgresql://test:test@localhost/testdb'
        assert settings.OPENSEARCH_HOST == 'localhost'
        assert settings.OPENSEARCH_PORT == '9200'
        assert settings.OPENSEARCH_USER == 'admin'
        assert settings.OPENSEARCH_PASSWORD == 'admin123'

    def test_settings_default_database_uri(self, monkeypatch):
        """Test Settings uses default sqlite:// when no database URI is provided"""
        # Arrange: Clear any existing database URI
        monkeypatch.delenv('SQLALCHEMY_DATABASE_URI', raising=False)
        monkeypatch.delenv('ENV_SECRETS', raising=False)

        # Clear the lru_cache
        get_settings.cache_clear()

        # Act
        settings = get_settings()

        # Assert: Should default to sqlite://
        assert settings.SQLALCHEMY_DATABASE_URI == 'sqlite://'

    @patch('core.config.get_secret')
    def test_settings_fallback_to_secrets(self, mock_get_secret, monkeypatch):
        """Test Settings falls back to AWS Secrets Manager when env vars not set"""
        # Arrange: Clear environment variables and set up secrets
        monkeypatch.delenv('SQLALCHEMY_DATABASE_URI', raising=False)
        monkeypatch.delenv('OPENSEARCH_HOST', raising=False)
        monkeypatch.setenv('ENV_SECRETS', 'my-app-secrets')
        monkeypatch.setenv('AWS_REGION', 'us-east-1')

        # Mock get_secret to return test data
        mock_get_secret.return_value = {
            'SQLALCHEMY_DATABASE_URI': 'postgresql://secret:pass@db.example.com/prod',
            'OPENSEARCH_HOST': 'opensearch.example.com',
            'OPENSEARCH_PORT': '443',
            'OPENSEARCH_USER': 'secret_user',
            'OPENSEARCH_PASSWORD': 'secret_pass'
        }

        # Clear the lru_cache
        get_settings.cache_clear()

        # Act
        settings = get_settings()

        # Assert: Values should come from secrets
        assert settings.SQLALCHEMY_DATABASE_URI == 'postgresql://secret:pass@db.example.com/prod'
        assert settings.OPENSEARCH_HOST == 'opensearch.example.com'

        # Verify get_secret was called
        mock_get_secret.assert_called_once_with('my-app-secrets', 'us-east-1')

    def test_settings_aws_credentials(self, monkeypatch):
        """Test that AWS credentials are loaded from environment"""
        # Arrange
        monkeypatch.setenv('AWS_ACCESS_KEY_ID', 'AKIAIOSFODNN7EXAMPLE')
        monkeypatch.setenv('AWS_SECRET_ACCESS_KEY', 'wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY')
        monkeypatch.setenv('AWS_REGION', 'us-west-2')

        # Clear the lru_cache
        get_settings.cache_clear()

        # Act
        settings = get_settings()

        # Assert
        assert settings.AWS_ACCESS_KEY_ID == 'AKIAIOSFODNN7EXAMPLE'
        assert settings.AWS_SECRET_ACCESS_KEY == 'wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY'
        assert settings.AWS_REGION == 'us-west-2'

    def test_settings_bucket_uris(self, monkeypatch):
        """Test bucket URI configuration"""
        # Arrange: Set custom bucket URIs
        monkeypatch.setenv('DATA_BUCKET_URI', 's3://custom-data-bucket')
        monkeypatch.setenv('RESULTS_BUCKET_URI', 's3://custom-results-bucket')

        # Clear the lru_cache
        get_settings.cache_clear()

        # Act
        settings = get_settings()

        # Assert
        assert settings.DATA_BUCKET_URI == 's3://custom-data-bucket'
        assert settings.RESULTS_BUCKET_URI == 's3://custom-results-bucket'

    def test_settings_bucket_uris_defaults(self, monkeypatch):
        """Test bucket URIs use defaults when not set"""
        # Arrange: Clear bucket URI env vars
        monkeypatch.delenv('DATA_BUCKET_URI', raising=False)
        monkeypatch.delenv('RESULTS_BUCKET_URI', raising=False)

        # Clear the lru_cache
        get_settings.cache_clear()

        # Act
        settings = get_settings()

        # Assert: Should use defaults
        assert settings.DATA_BUCKET_URI == 's3://my-data-bucket'
        assert settings.RESULTS_BUCKET_URI == 's3://my-results-bucket'

    @patch('core.config.get_secret')
    def test_settings_secret_cache(self, mock_get_secret, monkeypatch):
        """Test that secrets are cached and not fetched multiple times"""
        # Arrange
        monkeypatch.delenv('OPENSEARCH_HOST', raising=False)
        monkeypatch.delenv('OPENSEARCH_USER', raising=False)
        monkeypatch.setenv('ENV_SECRETS', 'my-app-secrets')
        monkeypatch.setenv('AWS_REGION', 'us-east-1')

        mock_get_secret.return_value = {
            'OPENSEARCH_HOST': 'cached.example.com',
            'OPENSEARCH_USER': 'cached_user'
        }

        # Clear the lru_cache
        get_settings.cache_clear()

        # Act: Access multiple properties that would need secrets
        settings = get_settings()
        host1 = settings.OPENSEARCH_HOST
        user1 = settings.OPENSEARCH_USER
        host2 = settings.OPENSEARCH_HOST  # Access again

        # Assert: get_secret should only be called once due to caching
        assert mock_get_secret.call_count == 1
        assert host1 == 'cached.example.com'
        assert user1 == 'cached_user'
        assert host2 == 'cached.example.com'

    @patch('core.config.get_secret')
    def test_settings_handles_secret_fetch_error(self, mock_get_secret, monkeypatch):
        """Test that Settings gracefully handles errors when fetching secrets"""
        # Arrange: Make get_secret raise an exception
        monkeypatch.delenv('OPENSEARCH_HOST', raising=False)
        monkeypatch.setenv('ENV_SECRETS', 'my-app-secrets')
        monkeypatch.setenv('AWS_REGION', 'us-east-1')

        mock_get_secret.side_effect = ClientError(
            error_response={'Error': {'Code': 'AccessDenied', 'Message': 'Access denied'}},
            operation_name='GetSecretValue'
        )

        # Clear the lru_cache
        get_settings.cache_clear()

        # Act: Should not raise, should return None
        settings = get_settings()
        result = settings.OPENSEARCH_HOST

        # Assert: Should return None when secret fetch fails
        assert result is None
