"""
Database configuration
"""

from sqlmodel import create_engine, Session
from core.config import get_settings

# Connect to db
# Set echo=True to see SQL statements in logs

engine = create_engine(
    str(get_settings().SQLALCHEMY_DATABASE_URI),
    echo=False,
    pool_pre_ping=True,           # Test connections before using them
    pool_recycle=3600,             # Recycle connections after 1 hour (3600 seconds)
    pool_size=5,                   # Number of connections to maintain in pool
    max_overflow=10                # Max connections beyond pool_size
)

# Yield session
def get_session():
    with Session(engine) as session:
        yield session
