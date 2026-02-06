# Authentication System Documentation

## Overview

The NGS360 API now includes a comprehensive authentication system with:

- Local username/password authentication
- OAuth2 support for external providers (Google, GitHub, Microsoft)
- JWT-based access tokens with refresh token rotation
- Password reset via email
- Email verification
- Account security features (lockout, password policies)

## Quick Start

### 1. Install Dependencies

```bash
cd APIServer
uv sync
```

### 2. Configure Environment Variables

Create or update your `.env` file:

```bash
# JWT Configuration
JWT_SECRET_KEY=your-super-secret-key-change-in-production
JWT_ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=30
REFRESH_TOKEN_EXPIRE_DAYS=30

# Password Policy
PASSWORD_MIN_LENGTH=8
PASSWORD_REQUIRE_UPPERCASE=true
PASSWORD_REQUIRE_LOWERCASE=true
PASSWORD_REQUIRE_DIGIT=true
PASSWORD_REQUIRE_SPECIAL=false

# Account Lockout
MAX_FAILED_LOGIN_ATTEMPTS=5
ACCOUNT_LOCKOUT_DURATION_MINUTES=30

# Email Configuration (AWS SES)
EMAIL_ENABLED=true
FROM_EMAIL=noreply@yourdomain.com
FROM_NAME=NGS360
AWS_REGION=us-east-1

# Frontend URL (for email links)
FRONTEND_URL=http://localhost:3000

# OAuth2 - Google (optional)
OAUTH_GOOGLE_CLIENT_ID=your-google-client-id
OAUTH_GOOGLE_CLIENT_SECRET=your-google-client-secret

# OAuth2 - GitHub (optional)
OAUTH_GITHUB_CLIENT_ID=your-github-client-id
OAUTH_GITHUB_CLIENT_SECRET=your-github-client-secret

# OAuth2 - Microsoft (optional)
OAUTH_MICROSOFT_CLIENT_ID=your-microsoft-client-id
OAUTH_MICROSOFT_CLIENT_SECRET=your-microsoft-client-secret

# Dev
OAUTH_CLIENT_ID=your-corp-id
OAUTH_SECRETKEY=your-corp-client-secret
OAUTH_URL=your-corp-oauth-url

```

### 3. Run Database Migration

```bash
alembic upgrade head
```

### 4. Start the Server

```bash
fastapi dev main.py
```

## API Endpoints

### Authentication Endpoints

#### Register New User

```http
POST /api/v1/auth/register
Content-Type: application/json

{
  "email": "user@example.com",
  "username": "johndoe",
  "password": "SecurePass123",
  "full_name": "John Doe"
}
```

#### Login

```http
POST /api/v1/auth/login
Content-Type: application/x-www-form-urlencoded

username=user@example.com&password=SecurePass123
```

Response:

```json
{
  "access_token": "eyJ0eXAiOiJKV1QiLCJhbGc...",
  "refresh_token": "random-secure-token",
  "token_type": "bearer",
  "expires_in": 1800
}
```

#### Refresh Token

```http
POST /api/v1/auth/refresh
Content-Type: application/json

{
  "refresh_token": "your-refresh-token"
}
```

#### Logout

```http
POST /api/v1/auth/logout
Content-Type: application/json

{
  "refresh_token": "your-refresh-token"
}
```

#### Get Current User

```http
GET /api/v1/auth/me
Authorization: Bearer your-access-token
```

#### Request Password Reset

```http
POST /api/v1/auth/password-reset/request
Content-Type: application/json

{
  "email": "user@example.com"
}
```

#### Confirm Password Reset

```http
POST /api/v1/auth/password-reset/confirm
Content-Type: application/json

{
  "token": "reset-token-from-email",
  "new_password": "NewSecurePass123"
}
```

#### Change Password

```http
POST /api/v1/auth/password/change
Authorization: Bearer your-access-token
Content-Type: application/json

{
  "current_password": "OldPass123",
  "new_password": "NewPass123"
}
```

#### Verify Email

```http
POST /api/v1/auth/verify-email
Content-Type: application/json

{
  "token": "verification-token-from-email"
}
```

#### Resend Verification Email

```http
POST /api/v1/auth/resend-verification
Content-Type: application/json

{
  "email": "user@example.com"
}
```

### OAuth2 Endpoints

#### Initiate OAuth2 Flow
```http
GET /api/v1/auth/oauth/{provider}/authorize
```
Where `{provider}` is one of: `google`, `github`, `microsoft`

This redirects the user to the OAuth provider's authorization page.

#### OAuth2 Callback
```http
GET /api/v1/auth/oauth/{provider}/callback?code=auth-code&state=state-value
```

This endpoint is called by the OAuth provider after user authorization.

#### Link OAuth Provider to Account
```http
POST /api/v1/auth/oauth/{provider}/link
Authorization: Bearer your-access-token
Content-Type: application/json

{
  "code": "authorization-code"
}
```

#### Unlink OAuth Provider
```http
DELETE /api/v1/auth/oauth/{provider}/unlink
Authorization: Bearer your-access-token
```

## Protecting Endpoints

To require authentication on your endpoints, use the authentication dependencies:

```python
from api.auth.deps import CurrentUser, CurrentActiveUser, CurrentSuperuser

# Require any authenticated user
@router.get("/protected")
def protected_endpoint(current_user: CurrentUser):
    return {"user": current_user.email}

# Require active and verified user
@router.get("/active-only")
def active_only_endpoint(current_user: CurrentActiveUser):
    return {"user": current_user.email}

# Require superuser
@router.get("/admin-only")
def admin_only_endpoint(current_user: CurrentSuperuser):
    return {"user": current_user.email}
```

## OAuth2 Provider Setup

### Google OAuth2

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Create a new project or select existing
3. Enable Google+ API
4. Go to "Credentials" → "Create Credentials" → "OAuth 2.0 Client ID"
5. Application type: Web application
6. Authorized redirect URIs: `http://localhost:8000/api/v1/auth/oauth/google/callback`
7. Copy Client ID and Client Secret to `.env`

### GitHub OAuth2

1. Go to GitHub Settings → Developer settings → OAuth Apps
2. Click "New OAuth App"
3. Application name: NGS360
4. Homepage URL: `http://localhost:8000`
5. Authorization callback URL: `http://localhost:8000/api/v1/auth/oauth/github/callback`
6. Copy Client ID and Client Secret to `.env`

### Microsoft OAuth2

1. Go to [Azure Portal](https://portal.azure.com/)
2. Navigate to "Azure Active Directory" → "App registrations"
3. Click "New registration"
4. Name: NGS360
5. Supported account types: Accounts in any organizational directory and personal Microsoft accounts
6. Redirect URI: Web - `http://localhost:8000/api/v1/auth/oauth/microsoft/callback`
7. After creation, go to "Certificates & secrets" → "New client secret"
8. Copy Application (client) ID and Client Secret to `.env`

## Security Features

### Password Policy

Configurable password requirements:
- Minimum length (default: 8)
- Require uppercase letters (default: true)
- Require lowercase letters (default: true)
- Require digits (default: true)
- Require special characters (default: false)

### Account Lockout

After a configurable number of failed login attempts (default: 5), accounts are temporarily locked for a specified duration (default: 30 minutes).

### Token Security

- **Access Tokens**: Short-lived JWT tokens (default: 30 minutes)
- **Refresh Tokens**: Long-lived tokens stored in database (default: 30 days)
- **Token Rotation**: Refresh tokens are rotated on each use
- **Token Revocation**: Refresh tokens can be revoked (logout)

### Email Verification

New users must verify their email address before accessing protected resources. Verification tokens expire after 7 days.

### Password Reset

Password reset tokens are:
- Single-use only
- Expire after 1 hour
- Cryptographically secure random strings

## Testing

### Manual Testing with curl

Register a user:
```bash
curl -X POST http://localhost:8000/api/v1/auth/register \
  -H "Content-Type: application/json" \
  -d '{
    "email": "test@example.com",
    "username": "testuser",
    "password": "TestPass123",
    "full_name": "Test User"
  }'
```

Login:
```bash
curl -X POST http://localhost:8000/api/v1/auth/login \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "username=test@example.com&password=TestPass123"
```

Access protected endpoint:
```bash
curl -X GET http://localhost:8000/api/v1/auth/me \
  -H "Authorization: Bearer YOUR_ACCESS_TOKEN"
```

### Automated Tests

Run the test suite:
```bash
pytest tests/api/test_auth.py -v
```

## Troubleshooting

### Email Not Sending

1. Check `EMAIL_ENABLED=true` in `.env`
2. Verify AWS credentials are configured
3. Ensure FROM_EMAIL is verified in AWS SES
4. Check application logs for error messages

### OAuth2 Not Working

1. Verify client ID and secret are correct
2. Check redirect URI matches exactly (including http/https)
3. Ensure OAuth provider credentials are not expired
4. Check that the provider is enabled in their console

### Token Errors

1. Ensure `JWT_SECRET_KEY` is set and consistent
2. Check token expiration times
3. Verify database connectivity for refresh tokens
4. Clear expired tokens from database

### Account Locked

Wait for the lockout duration to expire, or manually reset in database:
```sql
UPDATE users SET failed_login_attempts = 0, locked_until = NULL 
WHERE email = 'user@example.com';
```

## Database Schema

### Users Table
- `id`: UUID primary key
- `user_id`: Human-readable ID (U-YYYYMMDD-NNNN)
- `email`: Unique email address
- `username`: Unique username
- `hashed_password`: Bcrypt hashed password (nullable for OAuth-only users)
- `full_name`: User's full name
- `is_active`: Account active flag
- `is_verified`: Email verified flag
- `is_superuser`: Superuser flag
- `created_at`, `updated_at`, `last_login`: Timestamps
- `failed_login_attempts`, `locked_until`: Security fields

### Refresh Tokens Table
- `id`: UUID primary key
- `user_id`: Foreign key to users
- `token`: Unique token string
- `expires_at`: Expiration timestamp
- `revoked`: Revocation flag
- `device_info`: Optional device information

### OAuth Providers Table
- `id`: UUID primary key
- `user_id`: Foreign key to users
- `provider_name`: Provider enum (google, github, microsoft)
- `provider_user_id`: User ID from provider
- `access_token`, `refresh_token`: OAuth tokens
- `token_expires_at`: Token expiration

### Password Reset Tokens Table
- `id`: UUID primary key
- `user_id`: Foreign key to users
- `token`: Unique reset token
- `expires_at`: Expiration (1 hour)
- `used`: Single-use flag

### Email Verification Tokens Table
- `id`: UUID primary key
- `user_id`: Foreign key to users
- `token`: Unique verification token
- `expires_at`: Expiration (7 days)
- `used`: Single-use flag

## Production Deployment

### Security Checklist

- [ ] Change `JWT_SECRET_KEY` to a strong random value
- [ ] Use HTTPS for all endpoints
- [ ] Configure CORS properly
- [ ] Set up rate limiting
- [ ] Enable email verification requirement
- [ ] Configure AWS SES for production
- [ ] Set up monitoring and alerting
- [ ] Review and adjust token expiration times
- [ ] Enable database backups
- [ ] Set up log aggregation

### Environment Variables for Production

```bash
# Use strong random secret
JWT_SECRET_KEY=$(openssl rand -hex 32)

# Adjust token lifetimes as needed
ACCESS_TOKEN_EXPIRE_MINUTES=15
REFRESH_TOKEN_EXPIRE_DAYS=7

# Enable all security features
PASSWORD_REQUIRE_SPECIAL=true
MAX_FAILED_LOGIN_ATTEMPTS=3

# Production URLs
FRONTEND_URL=https://yourdomain.com
FROM_EMAIL=noreply@yourdomain.com
```

## Support

For issues or questions:
1. Check the troubleshooting section above
2. Review the API documentation at `/docs`
3. Check application logs
4. Consult the implementation plan in `plans/authentication-implementation-plan.md`
