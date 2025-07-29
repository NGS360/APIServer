"""
Define application startup and shutdown procedures
"""
from contextlib import asynccontextmanager
from fastapi import FastAPI
#from core.config import get_settings
#from core.db import init_db, drop_tables
from core.logger import logger

# Handle startup/shutdown tasks
@asynccontextmanager
async def lifespan(app: FastAPI):
  # Startup
  logger.info("In lifespan...starting up")
  # Initialize database (if not done already)
  #try:
  #  logger.info("Initializing database, %s", get_settings().SQLALCHEMY_DATABASE_URI_MASKED_PASSWORD)
  #  init_db()
  #  logger.info("Database initialized successfully")
  #except Exception as e:
  #  logger.error(f"Database initialization failed: {e}")
    # Re-raise the exception to fail application startup
  #  raise RuntimeError(f"Cannot start application: database initialization failed - {str(e)}")

  logger.info("In lifespan...yield")
  try:
    yield
  finally:
    # Shutdown
    logger.info("In lifespan...shutting down")
    # Destroy database
    #logger.info("Dropping database tables, %s", get_settings().SQLALCHEMY_DATABASE_URI_MASKED_PASSWORD)
    #drop_tables()
