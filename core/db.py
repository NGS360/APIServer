"""
Database configuration
"""

from sqlmodel import create_engine, Session
from sqlalchemy import event
from core.config import get_settings

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


# For MySQL/MariaDB, enforce strict date handling on every new connection so
# invalid "zero dates" (e.g. '1000-00-01') can no longer be written. Existing
# bad rows are still returned on read and handled by ProjectPublic's validator;
# this prevents new ones from being introduced.
if database_uri.startswith("mysql"):
    @event.listens_for(engine, "connect")
    def _set_mysql_sql_mode(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        try:
            cursor.execute(
                "SET SESSION sql_mode=CONCAT(@@sql_mode, "
                "',NO_ZERO_DATE,NO_ZERO_IN_DATE,STRICT_TRANS_TABLES')"
            )
        finally:
            cursor.close()


# Yield session
def get_session():
    with Session(engine) as session:
        yield session
