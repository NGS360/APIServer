"""
Database configuration
"""
from sqlmodel import SQLModel, create_engine, Session
from core.config import get_settings

# Connect to db
# Set echo=True to see SQL statements in logs
engine = create_engine(str(get_settings().SQLALCHEMY_DATABASE_URI), echo=False)

# Yield session
def get_session():
    with Session(engine) as session:
        yield session