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
    for key, value in vars(get_settings()).items():
        if "SQLALCHEMY_DATABASE_URI" in key:
            logger.info(
                "  %s: %s", key, get_settings().SQLALCHEMY_DATABASE_URI_MASKED_PASSWORD
            )
        elif ("PASSWORD" in key or "SECRET" in key) and value is not None:
            logger.info("  %s: %s", key, "*****")
        else:
            logger.info("  %s: %s", key, value)

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
        # Destroy database
        # logger.info(
        #   "Dropping database tables, %s",
        #   get_settings().SQLALCHEMY_DATABASE_URI_MASKED_PASSWORD
        # )
        # drop_tables()
