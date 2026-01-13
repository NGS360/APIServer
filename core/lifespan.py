"""
Define application startup and shutdown procedures
"""

import os
from contextlib import asynccontextmanager
from fastapi import FastAPI
from sqlmodel import Session, select
from core.config import get_settings
from core.db import engine

# from core.db import init_db, drop_tables
from core.opensearch import get_opensearch_client, init_indexes
from core.logger import logger


def sync_env_to_settings():
    """
    Sync environment variables to database settings.
    Only updates settings that exist in the DB but have empty/null values.
    Database is the source of truth - env vars are only used to populate missing values.
    """
    from api.settings.models import Setting

    # List of setting keys to check
    setting_keys = [
        "DATA_BUCKET_URI",
        "RESULTS_BUCKET_URI",
        "DEMUX_WORKFLOW_CONFIGS_BUCKET_URI",
        "MANIFEST_VALIDATION_LAMBDA"
    ]

    with Session(engine) as session:
        for key in setting_keys:
            # Check if environment variable exists
            env_value = os.getenv(key)
            if not env_value:
                continue

            # Check if setting exists in DB
            setting = session.exec(
                select(Setting).where(Setting.key == key)
            ).first()

            if setting and (not setting.value or setting.value.strip() == ""):
                # Setting exists but value is empty/null - populate from env
                logger.info(f"Populating setting '{key}' from environment variable")
                setting.value = env_value
                session.add(setting)

        session.commit()


# Handle startup/shutdown tasks
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    logger.info("In lifespan...starting up")

    # Print configuration settings (mask sensitive info)
    logger.info("Configuration Settings:")

    # Helper function to log settings with sensitive value masking
    def _log_setting(key: str, value):
        """Log a setting, masking sensitive values like passwords and secrets"""
        if ("PASSWORD" in key or "SECRET" in key) and value is not None:
            logger.info("  %s: %s", key, "*****")
        elif "SQLALCHEMY_DATABASE_URI" in key and value is not None:
            # Mask password in database URI if present
            import re
            masked_value = re.sub(r"://(.*?):(.*?)@", r"://\1:*****@", value)
            logger.info("  %s: %s", key, masked_value)
        else:
            logger.info("  %s: %s", key, value)

    settings = get_settings()

    # Log computed fields first (they don't appear in vars())
    computed_fields = [
        "SQLALCHEMY_DATABASE_URI",
        "OPENSEARCH_HOST",
        "OPENSEARCH_PORT",
        "OPENSEARCH_USER",
        "OPENSEARCH_PASSWORD",
        "OPENSEARCH_USE_SSL",
        "OPENSEARCH_VERIFY_CERTS"
    ]
    for key in computed_fields:
        value = getattr(settings, key)
        _log_setting(key, value)

    # Log remaining settings
    for key, value in vars(settings).items():
        _log_setting(key, value)

    # Sync environment variables to database settings
    logger.info("Syncing environment variables to database settings...")
    try:
        sync_env_to_settings()
        logger.info("Environment variables synced successfully")
    except Exception as e:
        logger.warning(f"Failed to sync environment variables: {e}")

    # Initialize database (if not done already)
    # try:
    #  logger.info("Initializing database...")
    #  init_db()
    #  logger.info("Database initialized successfully")
    # except Exception as e:
    #  logger.error(f"Database initialization failed: {e}")
    # Re-raise the exception to fail application startup
    #  raise RuntimeError(f"Cannot start application: database initialization failed - {str(e)}")

    logger.info("Initializing OpenSearch indexes...")
    client = get_opensearch_client()
    init_indexes(client)

    logger.info("In lifespan...yield")
    try:
        yield
    finally:
        # Shutdown
        logger.info("In lifespan...shutting down")
