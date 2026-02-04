# Authentication Tests

This directory contains comprehensive unit tests for the authentication system.

## Running the Tests

### Run all authentication tests:
```bash
cd APIServer
pytest tests/api/test_auth.py -v
```

### Run with coverage:
```bash
pytest tests/api/test_auth.py -v --cov=api.auth --cov=core.security
```

### Run specific test class:
```bash
pytest tests/api/test_auth.py::TestUserRegistration -v
pytest tests/api/test_auth.py::TestUserLogin -v
pytest tests/api/test_auth.py::TestProtectedEndpoints -v
```

### Run specific test:
```bash
pytest tests/api/test_auth.py::TestUserRegistration::test_register_new_user -v
```

## Test Coverage

### Test Classes

1. **TestUserRegistration** - User registration functionality
   - ✅ Successful registration
   - ✅ Duplicate email prevention
   - ✅ Duplicate username prevention
   - ✅ Password strength validation

2. **TestUserLogin** - User login functionality
   - ✅ Successful login
   - ✅ Wrong password handling
   - ✅ Nonexistent user handling

3. **TestTokenRefresh** - Token refresh functionality
   - ✅ Successful token refresh
   - ✅ Invalid token handling
   - ✅ Token rotation (reuse prevention)

4. **TestProtectedEndpoints** - Authentication on protected routes
   - ✅ Access with valid token
   - ✅ Access without token (401)
   - ✅ Access with invalid token (401)

5. **TestLogout** - Logout functionality
   - ✅ Successful logout
   - ✅ Token revocation

6. **TestPasswordChange** - Password change functionality
   - ✅ Successful password change
   - ✅ Wrong current password handling

7. **TestPasswordReset** - Password reset functionality
   - ✅ Reset request
   - ✅ Email enumeration prevention

8. **TestAccountSecurity** - Security features
   - ✅ Account lockout after failed attempts

9. **TestSecurityUtilities** - Core security functions
   - ✅ Password hashing
   - ✅ Password verification
   - ✅ Password strength validation
   - ✅ JWT token creation and validation

## Test Database

Tests use an in-memory SQLite database that is:
- Created fresh for each test session
- Isolated from production data
- Fast and doesn't require setup

## Test Fixtures

### `session`
Provides a clean database session for each test.

### `client`
Provides a FastAPI TestClient with the test database.

### `test_user`
Creates a pre-registered test user with:
- Email: testuser@example.com
- Username: testuser
- Password: TestPassword123
- Status: Active and verified

## Example Test Output

```bash
$ pytest tests/api/test_auth.py -v

tests/api/test_auth.py::TestUserRegistration::test_register_new_user PASSED
tests/api/test_auth.py::TestUserRegistration::test_register_duplicate_email PASSED
tests/api/test_auth.py::TestUserRegistration::test_register_duplicate_username PASSED
tests/api/test_auth.py::TestUserRegistration::test_register_weak_password PASSED
tests/api/test_auth.py::TestUserLogin::test_login_success PASSED
tests/api/test_auth.py::TestUserLogin::test_login_wrong_password PASSED
tests/api/test_auth.py::TestUserLogin::test_login_nonexistent_user PASSED
tests/api/test_auth.py::TestTokenRefresh::test_refresh_token_success PASSED
tests/api/test_auth.py::TestTokenRefresh::test_refresh_invalid_token PASSED
tests/api/test_auth.py::TestTokenRefresh::test_refresh_token_reuse_fails PASSED
tests/api/test_auth.py::TestProtectedEndpoints::test_access_protected_endpoint_with_token PASSED
tests/api/test_auth.py::TestProtectedEndpoints::test_access_protected_endpoint_without_token PASSED
tests/api/test_auth.py::TestProtectedEndpoints::test_access_protected_endpoint_invalid_token PASSED
tests/api/test_auth.py::TestLogout::test_logout_success PASSED
tests/api/test_auth.py::TestPasswordChange::test_change_password_success PASSED
tests/api/test_auth.py::TestPasswordChange::test_change_password_wrong_current PASSED
tests/api/test_auth.py::TestPasswordReset::test_request_password_reset PASSED
tests/api/test_auth.py::TestPasswordReset::test_request_password_reset_nonexistent_email PASSED
tests/api/test_auth.py::TestAccountSecurity::test_account_lockout_after_failed_attempts PASSED
tests/api/test_auth.py::TestSecurityUtilities::test_password_hashing PASSED
tests/api/test_auth.py::TestSecurityUtilities::test_password_strength_validation PASSED
tests/api/test_auth.py::TestSecurityUtilities::test_jwt_token_creation_and_validation PASSED

======================== 22 passed in 2.34s ========================
```

## Adding New Tests

When adding new authentication features, follow this pattern:

```python
class TestNewFeature:
    """Test description"""

    def test_success_case(self, client: TestClient, test_user):
        """Test successful operation"""
        response = client.post("/api/v1/auth/new-endpoint", json={...})
        assert response.status_code == 200
        # Add assertions

    def test_failure_case(self, client: TestClient):
        """Test error handling"""
        response = client.post("/api/v1/auth/new-endpoint", json={...})
        assert response.status_code == 400
        # Add assertions
```

## Continuous Integration

These tests should be run:
- Before committing code
- In CI/CD pipeline
- Before deploying to production

## Test Configuration

Tests use the same configuration as the application but with:
- In-memory database
- Disabled email sending
- Fast password hashing (for speed)

## Troubleshooting

### Tests fail with import errors
```bash
# Make sure you're in the APIServer directory
cd APIServer
# Install test dependencies
uv sync --extra dev
```

### Tests fail with database errors
```bash
# The in-memory database should work automatically
# If issues persist, check that SQLModel is installed
uv sync
```

### Tests are slow
```bash
# Run tests in parallel (requires pytest-xdist)
pytest tests/api/test_auth.py -n auto
```
