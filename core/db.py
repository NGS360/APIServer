"""
Database configuration
"""

from sqlmodel import create_engine, Session
from alembic.config import Config
from alembic import command
from core.config import get_settings
from core.logger import logger

# Get database URI
database_uri = str(get_settings().SQLALCHEMY_DATABASE_URI)

# Configure engine with connection pool settings for non-SQLite databases
if database_uri.startswith('sqlite'):
    # SQLite: Use simple configuration (no pool parameters)
    engine = create_engine(database_uri, echo=False)
else:
    # PostgreSQL/MySQL: Use connection pool with keep-alive settings
    engine = create_engine(
        database_uri,
        echo=False,
        pool_pre_ping=True,      # Test connections before using them
        pool_recycle=3600,       # Recycle connections after 1 hour
        pool_size=5,             # Number of connections in pool
        max_overflow=10          # Max additional connections during spikes
    )


# Yield session
def get_session():
    with Session(engine) as session:
        yield session


def init_db():
    logger.info("Running database migrations...")
    alembic_cfg = Config("alembic.ini")
    try:
        command.upgrade(alembic_cfg, "head")
    except Exception as e:
        logger.error(f"Database migration failed: {e}")
        raise RuntimeError(f"Database migration failed: {e}")
    logger.info("Migrations completed successfully.")
