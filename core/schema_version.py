"""
Check at startup whether the database schema is at the revision this code expects.

Migrations are applied out of band, by an operator with a privileged credential --
the application's own database user holds DML grants only and cannot perform DDL.
That is the right privilege split, but it decouples deploying code from migrating
the schema, so nothing structurally prevents shipping code that expects a table
the database does not have.

This does not fix that. It makes it visible: on startup the applied revision is
compared with the newest revision in alembic/versions, and a mismatch is logged
loudly. Logged rather than fatal, because refusing to start would turn a
forgotten migration into an outage, and the failure mode this guards against is
usually partial -- most endpoints keep working while the ones touching new tables
return 500s.

Cheap: two queries and a directory read, once per worker at startup.
"""

from pathlib import Path

from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import Engine

from core.logger import logger

# alembic.ini lives at the repository root, one level above core/.
_ALEMBIC_INI = Path(__file__).resolve().parent.parent / "alembic.ini"


def get_applied_revision(engine: Engine) -> str | None:
    """The revision recorded in alembic_version, or None if unmigrated."""
    with engine.connect() as connection:
        return MigrationContext.configure(connection).get_current_revision()


def get_expected_revision() -> str | None:
    """The newest revision in alembic/versions, or None if it cannot be read."""
    if not _ALEMBIC_INI.exists():
        logger.warning("alembic.ini not found at %s; skipping schema check",
                       _ALEMBIC_INI)
        return None
    script = ScriptDirectory.from_config(Config(str(_ALEMBIC_INI)))
    heads = script.get_heads()
    if len(heads) > 1:
        # Multiple heads mean branching revisions that have not been merged;
        # there is no single expected schema, which is itself worth flagging.
        logger.error(
            "alembic has %d heads (%s); the migration history has diverged and "
            "needs a merge revision", len(heads), ", ".join(sorted(heads)),
        )
        return None
    return heads[0] if heads else None


def check_schema_version(engine: Engine) -> bool:
    """
    Compare applied and expected revisions, logging the outcome.

    Returns True when they agree or the comparison could not be made, False when
    the database is definitely not at the revision this code expects.
    """
    try:
        applied = get_applied_revision(engine)
        expected = get_expected_revision()
    except Exception as exc:
        # Never let a diagnostic prevent startup.
        logger.warning("Could not determine schema version: %s", exc)
        return True

    if expected is None:
        return True

    if applied == expected:
        logger.info("Database schema is at the expected revision (%s)", expected)
        return True

    if applied is None:
        logger.error(
            "Database has no alembic_version row; expected revision %s. "
            "Migrations are applied out of band -- run `alembic upgrade head` "
            "with a credential that has DDL privileges.", expected,
        )
        return False

    logger.error(
        "SCHEMA MISMATCH: database is at revision %s but this code expects %s. "
        "Endpoints touching newly added tables or columns will fail. Migrations "
        "are applied out of band -- run `alembic upgrade head` with a credential "
        "that has DDL privileges.", applied, expected,
    )
    return False
