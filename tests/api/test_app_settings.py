"""Test cases for the AppSettings DB-backed configuration service."""
from sqlmodel import Session

from api.settings.models import Setting
from core.app_settings import AppSettings


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

    # Create a fresh AppSettings instance and load
    app = AppSettings()
    app.load()

    assert app.is_loaded()
    assert app.get("TEST_STR") == "hello"
    assert app.get("TEST_INT") == "42"
    assert app.get("TEST_BOOL") == "true"


def test_app_settings_get_default(session: Session):
    """Test that get() returns default when key not found."""
    app = AppSettings()
    app.load()

    assert app.get("NONEXISTENT") is None
    assert app.get("NONEXISTENT", "fallback") == "fallback"


def test_app_settings_get_int(session: Session):
    """Test get_int() typed accessor."""
    session.add(Setting(key="MY_INT", value="99", name="My Int"))
    session.add(Setting(key="BAD_INT", value="notanumber", name="Bad"))
    session.add(Setting(key="EMPTY_INT", value="", name="Empty"))
    session.commit()

    app = AppSettings()
    app.load()

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
    app.load()

    assert app.get_bool("BOOL_TRUE") is True
    assert app.get_bool("BOOL_YES") is True
    assert app.get_bool("BOOL_ONE") is True
    assert app.get_bool("BOOL_FALSE") is False
    assert app.get_bool("BOOL_EMPTY") is False
    assert app.get_bool("BOOL_EMPTY", default=True) is True
    assert app.get_bool("MISSING_BOOL") is False
    assert app.get_bool("MISSING_BOOL", default=True) is True


def test_app_settings_invalidate(session: Session):
    """Test that invalidate() reloads settings from DB."""
    session.add(Setting(key="RELOAD_TEST", value="original", name="Reload"))
    session.commit()

    app = AppSettings()
    app.load()
    assert app.get("RELOAD_TEST") == "original"

    # Update the value in DB
    setting = session.get(Setting, "RELOAD_TEST")
    setting.value = "updated"
    session.add(setting)
    session.commit()

    # Before invalidate, cache still has old value
    assert app.get("RELOAD_TEST") == "original"

    # After invalidate, new value is picked up
    app.invalidate()
    assert app.get("RELOAD_TEST") == "updated"


def test_app_settings_keys(session: Session):
    """Test keys() method returns all loaded keys."""
    session.add(Setting(key="KEY_A", value="a", name="A"))
    session.add(Setting(key="KEY_B", value="b", name="B"))
    session.commit()

    app = AppSettings()
    app.load()

    keys = app.keys()
    assert "KEY_A" in keys
    assert "KEY_B" in keys


def test_app_settings_lazy_load(session: Session):
    """Test that get() triggers lazy load if not loaded."""
    session.add(Setting(key="LAZY_KEY", value="lazy_val", name="Lazy"))
    session.commit()

    app = AppSettings()
    assert not app.is_loaded()

    # get() should trigger lazy load
    val = app.get("LAZY_KEY")
    assert val == "lazy_val"
    assert app.is_loaded()
