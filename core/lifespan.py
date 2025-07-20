"""
Define application startup and shutdown procedures
"""
from fastapi import FastAPI
from core.init_db import main as init_db
from core.db import drop_tables
from core.logger import logger

# Handle startup/shutdown tasks
async def lifespan(app: FastAPI):
  # Startup
  # Initialize database (if not done already)
  try:
    init_db()
    logger.info("Database initialized successfully")
  except Exception as e:
    logger.error(f"Database initialization failed: {e}")
    # Re-raise the exception to fail application startup
    raise RuntimeError(f"Cannot start application: database initialization failed - {str(e)}")

  yield
  # Shutdown

  # Destroy database
  drop_tables()
