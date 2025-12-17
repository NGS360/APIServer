"""
Define application startup and shutdown procedures
"""

from contextlib import asynccontextmanager
from fastapi import FastAPI
from core.config import get_settings

# from core.db import init_db, drop_tables
from core.opensearch import get_opensearch_client, init_indexes
from core.logger import logger


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
    computed_fields = {
        "SQLALCHEMY_DATABASE_URI": settings.SQLALCHEMY_DATABASE_URI,
        "OPENSEARCH_HOST": settings.OPENSEARCH_HOST,
        "OPENSEARCH_PORT": settings.OPENSEARCH_PORT,
        "OPENSEARCH_USER": settings.OPENSEARCH_USER,
        "OPENSEARCH_PASSWORD": settings.OPENSEARCH_PASSWORD,
        "OPENSEARCH_USE_SSL": settings.OPENSEARCH_USE_SSL,
        "OPENSEARCH_VERIFY_CERTS": settings.OPENSEARCH_VERIFY_CERTS,
    }

    for key, value in computed_fields.items():
        _log_setting(key, value)

    # Log remaining settings
    for key, value in vars(settings).items():
        _log_setting(key, value)

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
