"""
Define application startup and shutdown procedures
"""
from fastapi import FastAPI
from core.init_db import main as init_db
from core.db import drop_tables

# Handle startup/shutdown tasks
async def lifespan(app: FastAPI):
  # Startup
  # Initialize database (if not done already)
  try:
    init_db()
  except Exception as e:
    pass

  yield
  # Shutdown

  # Destroy database
  drop_tables()