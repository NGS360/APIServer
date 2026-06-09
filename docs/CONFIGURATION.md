# Configuration Architecture

## Overview

The NGS360 API Server uses a two-tier configuration system:

1. **Bootstrap Configuration** — Minimal env vars needed before the database is available
2. **DB-Backed Settings** — All runtime configuration stored in the `setting` table

The database is the **sole source of truth** for runtime settings. There is no env-var fallback once settings are loaded from the DB.

---

## Bootstrap Environment Variables

These must be set in the environment (`.env` file, Docker env, or AWS Secrets Manager):

| Variable | Required | Default | Purpose |
|----------|----------|---------|---------|
| `SQLALCHEMY_DATABASE_URI` | Yes | `sqlite://` | Database connection string |
| `AWS_REGION` | No | `us-east-1` | AWS SDK region |
| `AWS_ACCESS_KEY_ID` | No | — | AWS credentials |
| `AWS_SECRET_ACCESS_KEY` | No | — | AWS credentials |
| `ENV_SECRETS` | No | — | AWS Secrets Manager secret name |
| `LOG_LEVEL` | No | `INFO` | Application log level |
| `client_origin` | No | — | CORS allowed origin for frontend |

Access in code:
```python
from core.config import get_settings

bootstrap = get_settings()
db_uri = bootstrap.SQLALCHEMY_DATABASE_URI
```

---

## DB-Backed Runtime Settings

All other settings are stored in the `setting` database table and accessed via the `AppSettings` singleton.

### Accessing Settings in Code

```python
from core.app_settings import app_settings

# String value
jwt_key = app_settings.get("JWT_SECRET_KEY")

# Integer value  
expire_minutes = app_settings.get_int("ACCESS_TOKEN_EXPIRE_MINUTES", default=30)

# Boolean value
email_enabled = app_settings.get_bool("EMAIL_ENABLED")
```

### Available Setting Categories

#### Authentication (`auth`)
- `JWT_SECRET_KEY` — Secret key for JWT signing
- `JWT_ALGORITHM` — JWT algorithm (default: HS256)
- `ACCESS_TOKEN_EXPIRE_MINUTES` — Access token TTL in minutes
- `REFRESH_TOKEN_EXPIRE_DAYS` — Refresh token TTL in days

#### Security (`security`)
- `PASSWORD_MIN_LENGTH` — Minimum password length
- `PASSWORD_REQUIRE_UPPERCASE` — Require uppercase letters
- `PASSWORD_REQUIRE_LOWERCASE` — Require lowercase letters
- `PASSWORD_REQUIRE_DIGIT` — Require digits
- `PASSWORD_REQUIRE_SPECIAL` — Require special characters
- `MAX_FAILED_LOGIN_ATTEMPTS` — Attempts before lockout
- `ACCOUNT_LOCKOUT_DURATION_MINUTES` — Lockout duration

#### Email (`email`)
- `EMAIL_ENABLED` — Enable/disable email sending
- `FROM_EMAIL` — Sender email address
- `FROM_NAME` — Sender display name
- `FRONTEND_URL` — Frontend URL for email links
- `MAIL_SERVER` — SMTP server hostname
- `MAIL_PORT` — SMTP server port
- `MAIL_USERNAME` — SMTP auth username
- `MAIL_PASSWORD` — SMTP auth password
- `MAIL_USE_TLS` — Use TLS for SMTP
- `MAIL_ADMINS` — Admin email addresses

#### OpenSearch (`opensearch`)
- `OPENSEARCH_HOST` — Server hostname
- `OPENSEARCH_PORT` — Server port
- `OPENSEARCH_USER` — Auth username
- `OPENSEARCH_PASSWORD` — Auth password
- `OPENSEARCH_USE_SSL` — Use SSL connections
- `OPENSEARCH_VERIFY_CERTS` — Verify SSL certificates

#### Storage (`storage`)
- `STORAGE_BACKEND` — Storage type (s3 or local)
- `STORAGE_ROOT_PATH` — Root storage URI

#### OAuth2 (`oauth`)
- `OAUTH_GOOGLE_CLIENT_ID` / `OAUTH_GOOGLE_CLIENT_SECRET`
- `OAUTH_GITHUB_CLIENT_ID` / `OAUTH_GITHUB_CLIENT_SECRET`
- `OAUTH_MICROSOFT_CLIENT_ID` / `OAUTH_MICROSOFT_CLIENT_SECRET`
- `OAUTH_CORP_NAME` — Corporate SSO provider slug
- `OAUTH_CORP_DISPLAY_NAME` — Corporate SSO display name
- `OAUTH_CORP_CLIENT_ID` / `OAUTH_CORP_CLIENT_SECRET`
- `OAUTH_CORP_AUTHORIZE_URL` / `OAUTH_CORP_TOKEN_URL` / `OAUTH_CORP_USERINFO_URL`
- `OAUTH_CORP_SCOPES` — Comma-separated OAuth scopes

#### LDAP (`ldap`)
- `LDAP_ENABLED` — Enable LDAP user search
- `LDAP_SERVER` — LDAP server URL
- `LDAP_PORT` — LDAP server port
- `LDAP_USE_SSL` — Use SSL for LDAP
- `LDAP_BIND_DN` — Service account DN
- `LDAP_BIND_PASSWORD` — Service account password
- `LDAP_BASE_DN` — Base DN for searches
- `LDAP_USER_SEARCH_FILTER` — Search filter template
- `LDAP_USER_ATTRIBUTES` — Attributes to retrieve
- `LDAP_TIMEOUT` — Connection timeout in seconds

#### Project Settings (`project settings`)
- `DATA_BUCKET_URI` — S3 bucket for NGS data
- `RESULTS_BUCKET_URI` — S3 bucket for results
- `DEMUX_WORKFLOW_CONFIGS_BUCKET_URI` — Demux config bucket
- `PROJECT_WORKFLOW_CONFIGS_BUCKET_URI` — Project workflow configs
- `VENDOR_INGESTION_CONFIG` — Vendor ingestion configuration
- `MANIFEST_VALIDATION_LAMBDA` — Lambda ARN for validation

---

## Managing Settings

### Via API

```bash
# Get a setting
GET /api/v1/settings/JWT_ALGORITHM

# Update a setting
PUT /api/v1/settings/JWT_ALGORITHM
{"value": "HS384"}

# Get settings by category
GET /api/v1/settings?tag_key=category&tag_value=auth
```

### Migration from Environment Variables

On first startup after upgrading to the DB-backed settings system:

1. The Alembic migration seeds all setting rows with sensible defaults
2. `sync_env_to_settings()` runs during startup and copies env var values into any DB settings that have empty values
3. After this one-time sync, env vars for these settings can be removed from your deployment configuration

This means existing deployments with env vars configured will automatically migrate their values into the database.

---

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│                    Application Startup                    │
├─────────────────────────────────────────────────────────┤
│ 1. Load bootstrap env vars (core/config.py)             │
│ 2. Connect to database                                   │
│ 3. Run Alembic migrations (seeds setting rows)          │
│ 4. sync_env_to_settings() — one-time env→DB populate    │
│ 5. app_settings.load() — cache all settings in memory   │
│ 6. Initialize OpenSearch, start serving requests         │
└─────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────┐
│                    Runtime                                │
├─────────────────────────────────────────────────────────┤
│ • All modules read from app_settings singleton          │
│ • PUT /api/v1/settings/{key} → updates DB + invalidates │
│   in-memory cache                                        │
│ • No per-request DB queries for settings                │
└─────────────────────────────────────────────────────────┘
```

---

## Key Files

| File | Purpose |
|------|---------|
| [`core/config.py`](../core/config.py) | Bootstrap-only settings (env vars) |
| [`core/app_settings.py`](../core/app_settings.py) | DB-backed settings singleton with cache |
| [`core/lifespan.py`](../core/lifespan.py) | Startup: env sync + cache warm |
| [`api/settings/models.py`](../api/settings/models.py) | Setting DB model |
| [`api/settings/services.py`](../api/settings/services.py) | CRUD + cache invalidation |
| [`api/settings/routes.py`](../api/settings/routes.py) | REST API for settings |
