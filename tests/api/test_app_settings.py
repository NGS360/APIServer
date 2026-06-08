"""Test cases for the AppSettings DB-backed configuration service."""
from unittest.mock import patch

from sqlmodel import Session

from api.settings.models import Setting
from core.app_settings import AppSettings


def _get_test_bind(session: Session):
    """Extract the test bind (connection or engine) from a session fixture."""
    return session.get_bind()


def test_app_settings_load(session: Session):
    """Test that AppSettings loads settings from DB."""
    # Create test settings
    settings = [
        Setting(key="TEST_STR", value="hello", name="Test String"),
        Setting(key="TEST_INT", value="42", name="Test Int"),
        Setting(key="TEST_BOOL", value="true", name="Test Bool"),
    ]
    for s in settings:
        session.add(s)
    session.commit()

    # Create a fresh AppSettings instance and load from test bind
    app = AppSettings()
    app.load(bind=_get_test_bind(session))

    assert app.is_loaded()
    assert app.get("TEST_STR") == "hello"
    assert app.get("TEST_INT") == "42"
    assert app.get("TEST_BOOL") == "true"


def test_app_settings_get_default(session: Session):
    """Test that get() returns default when key not found."""
    app = AppSettings()
    app.load(bind=_get_test_bind(session))

    assert app.get("NONEXISTENT") is None
    assert app.get("NONEXISTENT", "fallback") == "fallback"


def test_app_settings_get_int(session: Session):
    """Test get_int() typed accessor."""
    session.add(Setting(key="MY_INT", value="99", name="My Int"))
    session.add(Setting(key="BAD_INT", value="notanumber", name="Bad"))
    session.add(Setting(key="EMPTY_INT", value="", name="Empty"))
    session.commit()

    app = AppSettings()
    app.load(bind=_get_test_bind(session))

    assert app.get_int("MY_INT") == 99
    assert app.get_int("BAD_INT", default=7) == 7
    assert app.get_int("EMPTY_INT", default=5) == 5
    assert app.get_int("MISSING_INT", default=10) == 10


def test_app_settings_get_bool(session: Session):
    """Test get_bool() typed accessor."""
    session.add(Setting(key="BOOL_TRUE", value="true", name="True"))
    session.add(Setting(key="BOOL_YES", value="yes", name="Yes"))
    session.add(Setting(key="BOOL_ONE", value="1", name="One"))
    session.add(Setting(key="BOOL_FALSE", value="false", name="False"))
    session.add(Setting(key="BOOL_EMPTY", value="", name="Empty"))
    session.commit()

    app = AppSettings()
    app.load(bind=_get_test_bind(session))

    assert app.get_bool("BOOL_TRUE") is True
    assert app.get_bool("BOOL_YES") is True
    assert app.get_bool("BOOL_ONE") is True
    assert app.get_bool("BOOL_FALSE") is False
    assert app.get_bool("BOOL_EMPTY") is False
    assert app.get_bool("BOOL_EMPTY", default=True) is True
    assert app.get_bool("MISSING_BOOL") is False
    assert app.get_bool("MISSING_BOOL", default=True) is True


def test_app_settings_invalidate():
    """Test that invalidate() clears cache, marks as unloaded, then reloads.

    Uses direct cache manipulation to verify the invalidation mechanism
    without relying on SQLite StaticPool transaction isolation.
    """
    app = AppSettings()
    # Pre-populate cache manually
    app._cache = {"KEY_A": "value_a", "KEY_B": "value_b"}
    app._loaded = True

    assert app.get("KEY_A") == "value_a"

    # Patch load() to simulate a DB reload with new data
    def mock_reload(bind=None):
        app._cache = {"KEY_A": "new_value_a", "KEY_C": "value_c"}
        app._loaded = True

    with patch.object(app, "load", side_effect=mock_reload):
        app.invalidate()

    # After invalidate:
    # - old KEY_B is gone (cache was cleared then reloaded)
    # - KEY_A has new value
    # - KEY_C appeared
    assert app.get("KEY_A") == "new_value_a"
    assert app.get("KEY_B") is None
    assert app.get("KEY_C") == "value_c"
    assert app.is_loaded()


def test_app_settings_keys(session: Session):
    """Test keys() method returns all loaded keys."""
    session.add(Setting(key="KEY_A", value="a", name="A"))
    session.add(Setting(key="KEY_B", value="b", name="B"))
    session.commit()

    app = AppSettings()
    app.load(bind=_get_test_bind(session))

    keys = app.keys()
    assert "KEY_A" in keys
    assert "KEY_B" in keys


def test_app_settings_lazy_load(session: Session):
    """Test that get() triggers lazy load if not loaded.

    Note: Lazy load uses the default engine (core.db.engine). In test
    environments we must explicitly set _engine_override to use the
    test DB. This test verifies the _engine_override path.
    """
    session.add(Setting(key="LAZY_KEY", value="lazy_val", name="Lazy"))
    session.commit()

    app = AppSettings()
    assert not app.is_loaded()

    # Explicitly set engine override without calling load
    app._engine_override = _get_test_bind(session)

    # get() should trigger lazy load using the overridden bind
    val = app.get("LAZY_KEY")
    assert val == "lazy_val"
    assert app.is_loaded()
