"""
Database configuration
"""
from sqlmodel import SQLModel, create_engine, Session
from core.config import settings

# Connect to db
# Set echo=True to see SQL statements in logs
engine = create_engine(str(settings.SQLALCHEMY_DATABASE_URI), echo=False)

# Create db and tables
def create_db_and_tables():
    SQLModel.metadata.create_all(engine)

# Drop tables
def drop_tables():
    SQLModel.metadata.drop_all(engine)

# Yield session
def get_session():
    with Session(engine) as session:
        yield session