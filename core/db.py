"""
Database configuration
"""
from sqlmodel import SQLModel, create_engine, Session
from core.config import get_settings

# Create engine lazily to allow test configuration to be applied
_engine = None

def get_engine():
    """
    Get or create the database engine.
    This lazy initialization allows test settings to be applied properly.
    """
    global _engine
    if _engine is None:
        _engine = create_engine(str(get_settings().SQLALCHEMY_DATABASE_URI), echo=False)
    return _engine

def reset_engine():
    """
    Reset the engine to None.
    This is useful for tests that need to switch between different settings.
    """
    global _engine
    _engine = None

# Yield session
def get_session():
    with Session(get_engine()) as session:
        yield session