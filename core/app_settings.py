"""
DB-backed application settings with in-memory caching.

This module provides the AppSettings singleton that reads all runtime
configuration from the `setting` DB table. Settings are loaded once at
startup and cached in-process. The cache is invalidated when settings
are updated via the API.

Usage:
    from core.app_settings import app_settings

    # String access
    jwt_key = app_settings.get("JWT_SECRET_KEY")

    # Typed helpers
    expire = app_settings.get_int("ACCESS_TOKEN_EXPIRE_MINUTES")
    enabled = app_settings.get_bool("EMAIL_ENABLED")
"""

import logging

from sqlmodel import Session, select

logger = logging.getLogger(__name__)


class AppSettings:
    """Cached, typed reader for DB-backed settings."""

    def __init__(self):
        self._cache: dict[str, str] = {}
        self._loaded = False

    def load(self) -> None:
        """Load all settings from DB into memory. Call once at startup."""
        from core.db import engine
        from api.settings.models import Setting

        with Session(engine) as session:
            settings = session.exec(select(Setting)).all()
            self._cache = {s.key: s.value for s in settings}
            self._loaded = True
            logger.info(
                "AppSettings loaded %d settings from database", len(self._cache)
            )

    def invalidate(self) -> None:
        """Clear cache and reload from DB. Call after settings are updated."""
        self._cache.clear()
        self._loaded = False
        self.load()

    def get(self, key: str, default: str | None = None) -> str | None:
        """Get raw string value."""
        if not self._loaded:
            self.load()
        return self._cache.get(key, default)

    def get_int(self, key: str, default: int = 0) -> int:
        """Get integer value."""
        val = self.get(key)
        if val is None or val.strip() == "":
            return default
        try:
            return int(val)
        except (ValueError, TypeError):
            logger.warning(
                "Setting '%s' has non-integer value '%s', returning default %d",
                key, val, default
            )
            return default

    def get_bool(self, key: str, default: bool = False) -> bool:
        """Get boolean value (true/1/yes = True)."""
        val = self.get(key)
        if val is None or val.strip() == "":
            return default
        return val.lower().strip() in ("true", "1", "yes")

    def is_loaded(self) -> bool:
        """Check if settings have been loaded from DB."""
        return self._loaded

    def keys(self) -> list[str]:
        """Return all loaded setting keys."""
        if not self._loaded:
            self.load()
        return list(self._cache.keys())


# Module-level singleton
app_settings = AppSettings()
