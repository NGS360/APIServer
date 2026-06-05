"""Seed all runtime settings into DB

Revision ID: a1b2c3d4e5f6
Revises: 983b2235ef87
Create Date: 2026-06-05 12:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, Sequence[str], None] = '983b2235ef87'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# All settings to seed into the DB
SETTINGS_TO_SEED = [
    # JWT / Auth
    {
        'key': 'JWT_SECRET_KEY',
        'value': 'change-this-secret-key-in-production',
        'name': 'JWT Secret Key',
        'description': 'Secret key used to sign JWT access tokens',
        'tags': [{'key': 'category', 'value': 'auth'}]
    },
    {
        'key': 'JWT_ALGORITHM',
        'value': 'HS256',
        'name': 'JWT Algorithm',
        'description': 'Algorithm used for JWT token signing',
        'tags': [{'key': 'category', 'value': 'auth'}]
    },
    {
        'key': 'ACCESS_TOKEN_EXPIRE_MINUTES',
        'value': '30',
        'name': 'Access Token Expiry (minutes)',
        'description': 'Number of minutes before an access token expires',
        'tags': [{'key': 'category', 'value': 'auth'}]
    },
    {
        'key': 'REFRESH_TOKEN_EXPIRE_DAYS',
        'value': '30',
        'name': 'Refresh Token Expiry (days)',
        'description': 'Number of days before a refresh token expires',
        'tags': [{'key': 'category', 'value': 'auth'}]
    },
    # Password Policy
    {
        'key': 'PASSWORD_MIN_LENGTH',
        'value': '8',
        'name': 'Password Minimum Length',
        'description': 'Minimum number of characters required for passwords',
        'tags': [{'key': 'category', 'value': 'security'}]
    },
    {
        'key': 'PASSWORD_REQUIRE_UPPERCASE',
        'value': 'true',
        'name': 'Password Require Uppercase',
        'description': 'Whether passwords must contain at least one uppercase letter',
        'tags': [{'key': 'category', 'value': 'security'}]
    },
    {
        'key': 'PASSWORD_REQUIRE_LOWERCASE',
        'value': 'true',
        'name': 'Password Require Lowercase',
        'description': 'Whether passwords must contain at least one lowercase letter',
        'tags': [{'key': 'category', 'value': 'security'}]
    },
    {
        'key': 'PASSWORD_REQUIRE_DIGIT',
        'value': 'true',
        'name': 'Password Require Digit',
        'description': 'Whether passwords must contain at least one digit',
        'tags': [{'key': 'category', 'value': 'security'}]
    },
    {
        'key': 'PASSWORD_REQUIRE_SPECIAL',
        'value': 'false',
        'name': 'Password Require Special Character',
        'description': 'Whether passwords must contain at least one special character',
        'tags': [{'key': 'category', 'value': 'security'}]
    },
    # Account Lockout
    {
        'key': 'MAX_FAILED_LOGIN_ATTEMPTS',
        'value': '5',
        'name': 'Max Failed Login Attempts',
        'description': 'Number of failed login attempts before account is locked',
        'tags': [{'key': 'category', 'value': 'security'}]
    },
    {
        'key': 'ACCOUNT_LOCKOUT_DURATION_MINUTES',
        'value': '30',
        'name': 'Account Lockout Duration (minutes)',
        'description': (
            'Duration in minutes that an account remains locked'
            ' after too many failed attempts'
        ),
        'tags': [{'key': 'category', 'value': 'security'}]
    },
    # Email / SMTP
    {
        'key': 'EMAIL_ENABLED',
        'value': 'false',
        'name': 'Email Enabled',
        'description': 'Whether email sending is enabled',
        'tags': [{'key': 'category', 'value': 'email'}]
    },
    {
        'key': 'FROM_EMAIL',
        'value': 'noreply@example.com',
        'name': 'From Email Address',
        'description': 'Email address used as the sender for outgoing emails',
        'tags': [{'key': 'category', 'value': 'email'}]
    },
    {
        'key': 'FROM_NAME',
        'value': 'NGS360',
        'name': 'From Name',
        'description': 'Display name used as the sender for outgoing emails',
        'tags': [{'key': 'category', 'value': 'email'}]
    },
    {
        'key': 'FRONTEND_URL',
        'value': 'http://localhost:3000',
        'name': 'Frontend URL',
        'description': 'Base URL of the frontend application (used in email links)',
        'tags': [{'key': 'category', 'value': 'email'}]
    },
    {
        'key': 'MAIL_SERVER',
        'value': '',
        'name': 'Mail Server',
        'description': 'SMTP server hostname',
        'tags': [{'key': 'category', 'value': 'email'}]
    },
    {
        'key': 'MAIL_PORT',
        'value': '',
        'name': 'Mail Port',
        'description': 'SMTP server port number',
        'tags': [{'key': 'category', 'value': 'email'}]
    },
    {
        'key': 'MAIL_USERNAME',
        'value': '',
        'name': 'Mail Username',
        'description': 'SMTP authentication username',
        'tags': [{'key': 'category', 'value': 'email'}]
    },
    {
        'key': 'MAIL_PASSWORD',
        'value': '',
        'name': 'Mail Password',
        'description': 'SMTP authentication password',
        'tags': [{'key': 'category', 'value': 'email'}]
    },
    {
        'key': 'MAIL_USE_TLS',
        'value': 'false',
        'name': 'Mail Use TLS',
        'description': 'Whether to use TLS for SMTP connections',
        'tags': [{'key': 'category', 'value': 'email'}]
    },
    {
        'key': 'MAIL_ADMINS',
        'value': '',
        'name': 'Mail Admins',
        'description': 'Comma-separated list of admin email addresses',
        'tags': [{'key': 'category', 'value': 'email'}]
    },
    # OpenSearch
    {
        'key': 'OPENSEARCH_HOST',
        'value': '',
        'name': 'OpenSearch Host',
        'description': 'OpenSearch server hostname',
        'tags': [{'key': 'category', 'value': 'opensearch'}]
    },
    {
        'key': 'OPENSEARCH_PORT',
        'value': '',
        'name': 'OpenSearch Port',
        'description': 'OpenSearch server port',
        'tags': [{'key': 'category', 'value': 'opensearch'}]
    },
    {
        'key': 'OPENSEARCH_USER',
        'value': '',
        'name': 'OpenSearch User',
        'description': 'OpenSearch authentication username',
        'tags': [{'key': 'category', 'value': 'opensearch'}]
    },
    {
        'key': 'OPENSEARCH_PASSWORD',
        'value': '',
        'name': 'OpenSearch Password',
        'description': 'OpenSearch authentication password',
        'tags': [{'key': 'category', 'value': 'opensearch'}]
    },
    {
        'key': 'OPENSEARCH_USE_SSL',
        'value': 'true',
        'name': 'OpenSearch Use SSL',
        'description': 'Whether to use SSL for OpenSearch connections',
        'tags': [{'key': 'category', 'value': 'opensearch'}]
    },
    {
        'key': 'OPENSEARCH_VERIFY_CERTS',
        'value': 'false',
        'name': 'OpenSearch Verify Certificates',
        'description': 'Whether to verify SSL certificates for OpenSearch connections',
        'tags': [{'key': 'category', 'value': 'opensearch'}]
    },
    # Storage
    {
        'key': 'STORAGE_BACKEND',
        'value': 's3',
        'name': 'Storage Backend',
        'description': 'Storage backend type (s3 or local)',
        'tags': [{'key': 'category', 'value': 'storage'}]
    },
    {
        'key': 'STORAGE_ROOT_PATH',
        'value': 's3://my-storage-bucket',
        'name': 'Storage Root Path',
        'description': 'Root URI for file storage (e.g., s3://bucket-name)',
        'tags': [{'key': 'category', 'value': 'storage'}]
    },
    # OAuth2 - Google
    {
        'key': 'OAUTH_GOOGLE_CLIENT_ID',
        'value': '',
        'name': 'Google OAuth Client ID',
        'description': 'Client ID for Google OAuth2 integration',
        'tags': [{'key': 'category', 'value': 'oauth'}]
    },
    {
        'key': 'OAUTH_GOOGLE_CLIENT_SECRET',
        'value': '',
        'name': 'Google OAuth Client Secret',
        'description': 'Client secret for Google OAuth2 integration',
        'tags': [{'key': 'category', 'value': 'oauth'}]
    },
    # OAuth2 - GitHub
    {
        'key': 'OAUTH_GITHUB_CLIENT_ID',
        'value': '',
        'name': 'GitHub OAuth Client ID',
        'description': 'Client ID for GitHub OAuth2 integration',
        'tags': [{'key': 'category', 'value': 'oauth'}]
    },
    {
        'key': 'OAUTH_GITHUB_CLIENT_SECRET',
        'value': '',
        'name': 'GitHub OAuth Client Secret',
        'description': 'Client secret for GitHub OAuth2 integration',
        'tags': [{'key': 'category', 'value': 'oauth'}]
    },
    # OAuth2 - Microsoft
    {
        'key': 'OAUTH_MICROSOFT_CLIENT_ID',
        'value': '',
        'name': 'Microsoft OAuth Client ID',
        'description': 'Client ID for Microsoft OAuth2 integration',
        'tags': [{'key': 'category', 'value': 'oauth'}]
    },
    {
        'key': 'OAUTH_MICROSOFT_CLIENT_SECRET',
        'value': '',
        'name': 'Microsoft OAuth Client Secret',
        'description': 'Client secret for Microsoft OAuth2 integration',
        'tags': [{'key': 'category', 'value': 'oauth'}]
    },
    # OAuth2 - Corporate SSO
    {
        'key': 'OAUTH_CORP_NAME',
        'value': '',
        'name': 'Corporate OAuth Provider Name',
        'description': 'Internal name/slug for the corporate SSO provider',
        'tags': [{'key': 'category', 'value': 'oauth'}]
    },
    {
        'key': 'OAUTH_CORP_DISPLAY_NAME',
        'value': '',
        'name': 'Corporate OAuth Display Name',
        'description': 'Display name shown to users for the corporate SSO option',
        'tags': [{'key': 'category', 'value': 'oauth'}]
    },
    {
        'key': 'OAUTH_CORP_CLIENT_ID',
        'value': '',
        'name': 'Corporate OAuth Client ID',
        'description': 'Client ID for corporate SSO OAuth2 integration',
        'tags': [{'key': 'category', 'value': 'oauth'}]
    },
    {
        'key': 'OAUTH_CORP_CLIENT_SECRET',
        'value': '',
        'name': 'Corporate OAuth Client Secret',
        'description': 'Client secret for corporate SSO OAuth2 integration',
        'tags': [{'key': 'category', 'value': 'oauth'}]
    },
    {
        'key': 'OAUTH_CORP_AUTHORIZE_URL',
        'value': '',
        'name': 'Corporate OAuth Authorize URL',
        'description': 'Authorization endpoint URL for corporate SSO',
        'tags': [{'key': 'category', 'value': 'oauth'}]
    },
    {
        'key': 'OAUTH_CORP_TOKEN_URL',
        'value': '',
        'name': 'Corporate OAuth Token URL',
        'description': 'Token endpoint URL for corporate SSO',
        'tags': [{'key': 'category', 'value': 'oauth'}]
    },
    {
        'key': 'OAUTH_CORP_USERINFO_URL',
        'value': '',
        'name': 'Corporate OAuth Userinfo URL',
        'description': 'Userinfo endpoint URL for corporate SSO',
        'tags': [{'key': 'category', 'value': 'oauth'}]
    },
    {
        'key': 'OAUTH_CORP_SCOPES',
        'value': 'openid,email,profile',
        'name': 'Corporate OAuth Scopes',
        'description': 'Comma-separated OAuth2 scopes to request from corporate SSO',
        'tags': [{'key': 'category', 'value': 'oauth'}]
    },
    # LDAP
    {
        'key': 'LDAP_ENABLED',
        'value': 'false',
        'name': 'LDAP Enabled',
        'description': 'Whether LDAP user search is enabled',
        'tags': [{'key': 'category', 'value': 'ldap'}]
    },
    {
        'key': 'LDAP_SERVER',
        'value': '',
        'name': 'LDAP Server',
        'description': 'LDAP server URL (e.g., ldap://ldap.example.com)',
        'tags': [{'key': 'category', 'value': 'ldap'}]
    },
    {
        'key': 'LDAP_PORT',
        'value': '389',
        'name': 'LDAP Port',
        'description': 'LDAP server port (389 for LDAP, 636 for LDAPS)',
        'tags': [{'key': 'category', 'value': 'ldap'}]
    },
    {
        'key': 'LDAP_USE_SSL',
        'value': 'false',
        'name': 'LDAP Use SSL',
        'description': 'Whether to use SSL/TLS for LDAP connections',
        'tags': [{'key': 'category', 'value': 'ldap'}]
    },
    {
        'key': 'LDAP_BIND_DN',
        'value': '',
        'name': 'LDAP Bind DN',
        'description': 'Distinguished Name for LDAP bind (service account)',
        'tags': [{'key': 'category', 'value': 'ldap'}]
    },
    {
        'key': 'LDAP_BIND_PASSWORD',
        'value': '',
        'name': 'LDAP Bind Password',
        'description': 'Password for LDAP bind service account',
        'tags': [{'key': 'category', 'value': 'ldap'}]
    },
    {
        'key': 'LDAP_BASE_DN',
        'value': '',
        'name': 'LDAP Base DN',
        'description': 'Base DN for LDAP user search (e.g., ou=People,dc=example,dc=com)',
        'tags': [{'key': 'category', 'value': 'ldap'}]
    },
    {
        'key': 'LDAP_USER_SEARCH_FILTER',
        'value': '(|(cn=*{query}*)(mail=*{query}*)(uid=*{query}*))',
        'name': 'LDAP User Search Filter',
        'description': 'LDAP search filter template. Use {query} as placeholder.',
        'tags': [{'key': 'category', 'value': 'ldap'}]
    },
    {
        'key': 'LDAP_USER_ATTRIBUTES',
        'value': 'cn,mail,uid,displayName,department,title',
        'name': 'LDAP User Attributes',
        'description': 'Comma-separated LDAP attributes to retrieve in user searches',
        'tags': [{'key': 'category', 'value': 'ldap'}]
    },
    {
        'key': 'LDAP_TIMEOUT',
        'value': '10',
        'name': 'LDAP Timeout',
        'description': 'LDAP connection/search timeout in seconds',
        'tags': [{'key': 'category', 'value': 'ldap'}]
    },
]


def upgrade() -> None:
    """Seed all runtime configuration settings into the setting table."""
    settings_table = sa.table(
        'setting',
        sa.column('key', sa.String),
        sa.column('value', sa.String),
        sa.column('name', sa.String),
        sa.column('description', sa.String),
        sa.column('tags', sa.JSON),
    )

    # Only insert settings that don't already exist
    conn = op.get_bind()
    for setting in SETTINGS_TO_SEED:
        exists = conn.execute(
            sa.text("SELECT 1 FROM setting WHERE key = :key"),
            {"key": setting["key"]}
        ).fetchone()
        if not exists:
            op.bulk_insert(settings_table, [setting])


def downgrade() -> None:
    """Remove seeded runtime settings."""
    settings_table = sa.table(
        'setting',
        sa.column('key', sa.String),
    )
    keys_to_remove = [s['key'] for s in SETTINGS_TO_SEED]
    op.execute(
        settings_table.delete().where(
            settings_table.c.key.in_(keys_to_remove)
        )
    )
