# Testing Guide for NGS360 APIServer

## Mocking AWS boto3 Services

### Overview

This guide explains how to properly mock AWS boto3 services, specifically `boto3.session.Session()`, for testing purposes. This is essential for testing code that interacts with AWS services without making actual API calls.

### The boto3 Mocking Pattern

When testing functions that use boto3, you need to mock the entire chain of calls:

```
boto3.session.Session() → session.client() → client.method()
```

### Example: Mocking AWS Secrets Manager

The [`get_secret()`](../core/config.py:23) function in [`core/config.py`](../core/config.py:23) uses this pattern:

```python
session = boto3.session.Session()
client = session.client(service_name='secretsmanager', region_name=region_name)
response = client.get_secret_value(SecretId=secret_name)
```

#### Step-by-Step Mocking

1. **Import Required Modules**
```python
from unittest.mock import Mock, patch
from botocore.exceptions import ClientError
```

2. **Create the Mock Chain**
```python
@patch('core.config.boto3.session.Session')
def test_get_secret_success(mock_session_class):
    # Step 1: Create mock client with desired return value
    mock_client = Mock()
    mock_client.get_secret_value.return_value = {
        'SecretString': '{"key": "value"}'
    }
    
    # Step 2: Create mock session that returns the mock client
    mock_session = Mock()
    mock_session.client.return_value = mock_client
    
    # Step 3: Make Session class return the mock session
    mock_session_class.return_value = mock_session
    
    # Now call your function - it will use the mocked chain
    result = get_secret('my-secret', 'us-east-1')
```

3. **Verify Mock Calls**
```python
# Verify Session was instantiated
mock_session_class.assert_called_once()

# Verify client was created with correct parameters
mock_session.client.assert_called_once_with(
    service_name='secretsmanager',
    region_name='us-east-1'
)

# Verify the service method was called correctly
mock_client.get_secret_value.assert_called_once_with(
    SecretId='my-secret'
)
```

### Testing Error Scenarios

To test error handling, use `side_effect` to raise exceptions:

```python
@patch('core.config.boto3.session.Session')
def test_get_secret_client_error(mock_session_class):
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
    
    # Verify the exception is raised
    with pytest.raises(ClientError):
        get_secret('non-existent-secret', 'us-east-1')
```

### Testing Settings with Environment Variables

Use `monkeypatch` fixture to set/unset environment variables:

```python
def test_settings_with_env_vars(monkeypatch):
    # Set environment variables
    monkeypatch.setenv('SQLALCHEMY_DATABASE_URI', 'postgresql://test')
    monkeypatch.setenv('OPENSEARCH_HOST', 'localhost')
    
    # Clear the lru_cache to get fresh settings
    get_settings.cache_clear()
    
    settings = get_settings()
    assert settings.SQLALCHEMY_DATABASE_URI == 'postgresql://test'
```

### Testing Settings with AWS Secrets Fallback

Mock the `get_secret` function when testing Settings that fall back to AWS Secrets Manager:

```python
@patch('core.config.get_secret')
def test_settings_fallback_to_secrets(mock_get_secret, monkeypatch):
    # Clear environment variables
    monkeypatch.delenv('OPENSEARCH_HOST', raising=False)
    monkeypatch.setenv('ENV_SECRETS', 'my-app-secrets')
    monkeypatch.setenv('AWS_REGION', 'us-east-1')
    
    # Mock get_secret return value
    mock_get_secret.return_value = {
        'OPENSEARCH_HOST': 'opensearch.example.com'
    }
    
    get_settings.cache_clear()
    settings = get_settings()
    
    assert settings.OPENSEARCH_HOST == 'opensearch.example.com'
    mock_get_secret.assert_called_once_with('my-app-secrets', 'us-east-1')
```

## Test Structure

### Test Organization

Tests are organized into classes for better structure:

```python
class TestGetSecret:
    """Test suite for get_secret function"""
    
    def test_get_secret_success(self):
        """Test successful secret retrieval"""
        pass
    
    def test_get_secret_client_error(self):
        """Test error handling"""
        pass

class TestSettings:
    """Test suite for Settings class"""
    
    def test_settings_with_env_vars(self):
        """Test environment variable usage"""
        pass
```

### Test Coverage

The test suite covers:

1. **Success Scenarios**
   - Successful secret retrieval
   - Different AWS regions
   - Newline handling in secrets
   - Environment variable usage
   - Default values

2. **Error Scenarios**
   - ClientError exceptions
   - Missing secrets
   - Secret fetch failures

3. **Caching Behavior**
   - Secret caching to avoid multiple API calls
   - LRU cache clearing for fresh settings

4. **Configuration Priority**
   - Environment variables (highest priority)
   - AWS Secrets Manager (fallback)
   - Default values (last resort)

## Running Tests

```bash
# Run all tests in test_settings.py
python -m pytest tests/test_settings.py -v

# Run specific test class
python -m pytest tests/test_settings.py::TestGetSecret -v

# Run specific test
python -m pytest tests/test_settings.py::TestGetSecret::test_get_secret_success -v

# Run with coverage
python -m pytest tests/test_settings.py --cov=core.config --cov-report=html
```

## Best Practices

1. **Always patch at the import location**: Use `@patch('core.config.boto3.session.Session')` not `@patch('boto3.session.Session')`

2. **Clear caches between tests**: Use `get_settings.cache_clear()` when testing Settings

3. **Use descriptive test names**: Test names should clearly indicate what is being tested

4. **Test both success and failure paths**: Always test error handling

5. **Verify mock calls**: Use `assert_called_once_with()` to verify correct parameters

6. **Use monkeypatch for environment variables**: It automatically cleans up after tests

7. **Document complex mocking**: Add comments explaining the mock chain

## Common Pitfalls

1. **Forgetting to clear LRU cache**: Settings are cached, so clear the cache in tests
2. **Patching at wrong location**: Patch where the object is used, not where it's defined
3. **Not mocking the entire chain**: All levels (Session → client → method) must be mocked
4. **Assuming mock success**: Always verify mock calls with assertions

## Additional Resources

- [unittest.mock documentation](https://docs.python.org/3/library/unittest.mock.html)
- [pytest monkeypatch documentation](https://docs.pytest.org/en/stable/how-to/monkeypatch.html)
- [boto3 testing best practices](https://boto3.amazonaws.com/v1/documentation/api/latest/guide/testing.html)