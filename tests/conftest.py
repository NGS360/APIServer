"""
Pytest configuration and fixtures
"""
import os
import pytest
from fastapi.testclient import TestClient
from sqlmodel import SQLModel, Session, create_engine
from sqlmodel.pool import StaticPool

# Set testing mode environment variable BEFORE any imports
# This ensures test settings are used throughout the application
os.environ["SETTINGS_MODE"] = "test"

# Import after setting the environment variable
from main import app
from core.deps import get_db
from core.db import get_engine as app_get_engine, _engine
from core.config import get_test_settings, InMemoryDbSettings


@pytest.fixture(name="test_settings")
def test_settings_fixture():
    """
    Provides test settings configuration.
    """
    return get_test_settings()


@pytest.fixture(name="engine", autouse=True)
def engine_fixture():
    """
    Create a SQLite in-memory database engine for testing.
    This fixture runs automatically for all tests.
    """
    # Create a test-specific in-memory SQLite engine
    test_engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    
    # Override the application engine with our test engine
    global _engine
    _engine = test_engine
    
    # Create all tables
    SQLModel.metadata.create_all(test_engine)
    
    # Return the engine for use in other fixtures
    yield test_engine
    
    # Clean up after tests
    SQLModel.metadata.drop_all(test_engine)
    test_engine.dispose()


@pytest.fixture(name="session")
def session_fixture(engine):
    """
    Create a new database session for testing.
    """
    with Session(engine) as session:
        yield session


@pytest.fixture(name="client")
def client_fixture(session: Session):
    """
    Create a FastAPI TestClient with test database session.
    """
    def get_db_override():
        return session

    app.dependency_overrides[get_db] = get_db_override
    client = TestClient(app)
    yield client
    app.dependency_overrides.clear()
