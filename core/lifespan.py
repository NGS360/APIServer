"""
Define application startup and shutdown procedures
"""

import os
from contextlib import asynccontextmanager
from fastapi import FastAPI
from sqlmodel import Session, select
from core.config import get_settings
from core.db import engine
from core.app_settings import app_settings

from core.opensearch import get_opensearch_client, init_indexes
from core.logger import logger


# All setting keys that should be synced from env vars into the DB.
# On first startup after upgrade, if a DB setting has an empty value
# and the corresponding env var is set, the env var value is written
# into the DB. After that, DB is the sole source of truth.
ALL_SETTING_KEYS = [
    # Existing project/run settings
    "DATA_BUCKET_URI",
    "RESULTS_BUCKET_URI",
    "DEMUX_WORKFLOW_CONFIGS_BUCKET_URI",
    "MANIFEST_VALIDATION_LAMBDA",
    "PROJECT_WORKFLOW_CONFIGS_BUCKET_URI",
    "VENDOR_INGESTION_CONFIG",
    # JWT / Auth
    "JWT_SECRET_KEY",
    "JWT_ALGORITHM",
    "ACCESS_TOKEN_EXPIRE_MINUTES",
    "REFRESH_TOKEN_EXPIRE_DAYS",
    # Password Policy
    "PASSWORD_MIN_LENGTH",
    "PASSWORD_REQUIRE_UPPERCASE",
    "PASSWORD_REQUIRE_LOWERCASE",
    "PASSWORD_REQUIRE_DIGIT",
    "PASSWORD_REQUIRE_SPECIAL",
    # Account Lockout
    "MAX_FAILED_LOGIN_ATTEMPTS",
    "ACCOUNT_LOCKOUT_DURATION_MINUTES",
    # Email / SMTP
    "EMAIL_ENABLED",
    "FROM_EMAIL",
    "FROM_NAME",
    "FRONTEND_URL",
    "MAIL_SERVER",
    "MAIL_PORT",
    "MAIL_USERNAME",
    "MAIL_PASSWORD",
    "MAIL_USE_TLS",
    "MAIL_ADMINS",
    # OpenSearch
    "OPENSEARCH_HOST",
    "OPENSEARCH_PORT",
    "OPENSEARCH_USER",
    "OPENSEARCH_PASSWORD",
    "OPENSEARCH_USE_SSL",
    "OPENSEARCH_VERIFY_CERTS",
    # Storage
    "STORAGE_BACKEND",
    "STORAGE_ROOT_PATH",
    # OAuth2 - Google
    "OAUTH_GOOGLE_CLIENT_ID",
    "OAUTH_GOOGLE_CLIENT_SECRET",
    # OAuth2 - GitHub
    "OAUTH_GITHUB_CLIENT_ID",
    "OAUTH_GITHUB_CLIENT_SECRET",
    # OAuth2 - Microsoft
    "OAUTH_MICROSOFT_CLIENT_ID",
    "OAUTH_MICROSOFT_CLIENT_SECRET",
    # OAuth2 - Corporate SSO
    "OAUTH_CORP_NAME",
    "OAUTH_CORP_DISPLAY_NAME",
    "OAUTH_CORP_CLIENT_ID",
    "OAUTH_CORP_CLIENT_SECRET",
    "OAUTH_CORP_AUTHORIZE_URL",
    "OAUTH_CORP_TOKEN_URL",
    "OAUTH_CORP_USERINFO_URL",
    "OAUTH_CORP_SCOPES",
    # LDAP
    "LDAP_ENABLED",
    "LDAP_SERVER",
    "LDAP_PORT",
    "LDAP_USE_SSL",
    "LDAP_BIND_DN",
    "LDAP_BIND_PASSWORD",
    "LDAP_BASE_DN",
    "LDAP_USER_SEARCH_FILTER",
    "LDAP_USER_ATTRIBUTES",
    "LDAP_TIMEOUT",
]


def sync_env_to_settings():
    """
    Sync environment variables to database settings.
    Only updates settings that exist in the DB but have empty/null values.
    Database is the source of truth - env vars are only used to populate
    missing values on first startup after migration.
    """
    from api.settings.models import Setting

    with Session(engine) as session:
        for key in ALL_SETTING_KEYS:
            # Check if environment variable exists
            env_value = os.getenv(key)
            if not env_value:
                continue

            # Check if setting exists in DB
            setting = session.exec(
                select(Setting).where(Setting.key == key)
            ).first()

            if setting and (not setting.value or setting.value.strip() == ""):
                # Setting exists but value is empty - populate from env
                logger.info(
                    "Populating setting '%s' from environment variable",
                    key
                )
                setting.value = env_value
                session.add(setting)

        session.commit()


def _log_setting(key: str, value):
    """Log a setting, masking sensitive values"""
    if ("PASSWORD" in key or "SECRET" in key) and value is not None:
        logger.info("  %s: %s", key, "*****")
    elif "SQLALCHEMY_DATABASE_URI" in key and value is not None:
        import re
        masked_value = re.sub(
            r"://(.*?):(.*?)@", r"://\1:*****@", value
        )
        logger.info("  %s: %s", key, masked_value)
    else:
        logger.info("  %s: %s", key, value)



# Handle startup/shutdown tasks
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    logger.info("In lifespan...starting up")

    # Print bootstrap configuration
    logger.info("Bootstrap Configuration:")
    settings = get_settings()

    # Log bootstrap settings
    bootstrap_fields = [
        "SQLALCHEMY_DATABASE_URI",
        "AWS_REGION",
        "AWS_ACCESS_KEY_ID",
        "AWS_SECRET_ACCESS_KEY",
        "LOG_LEVEL",
    ]
    for key in bootstrap_fields:
        value = getattr(settings, key, None)
        _log_setting(key, value)
    _log_setting("client_origin", settings.client_origin)

    # If db is sqllite in memory, run migration scripts
    if settings.SQLALCHEMY_DATABASE_URI.startswith("sqlite://"):
        raise RuntimeError("SQLLite not supported.  Please use MySQL or PostgreSQL.")

    # Sync environment variables to database settings (one-time seeding)
    logger.info("Syncing environment variables to database settings...")
    try:
        sync_env_to_settings()
        logger.info("Environment variables synced successfully")
    except Exception as e:
        logger.warning(f"Failed to sync environment variables: {e}")

    # Load all DB settings into AppSettings cache
    logger.info("Loading application settings from database...")
    try:
        app_settings.load()
        logger.info(
            "AppSettings loaded: %d settings cached",
            len(app_settings.keys())
        )
    except Exception as e:
        logger.error(f"Failed to load AppSettings: {e}")
        raise RuntimeError(
            f"Cannot start application: failed to load settings - {e}"
        )

    # Log DB-backed settings (mask sensitive ones)
    logger.info("DB-Backed Settings:")
    for key in sorted(app_settings.keys()):
        value = app_settings.get(key)
        _log_setting(key, value)

    logger.info("Initializing OpenSearch indexes...")
    client = get_opensearch_client()
    init_indexes(client)

    logger.info("In lifespan...yield")
    try:
        yield
    finally:
        # Shutdown
        logger.info("In lifespan...shutting down")
