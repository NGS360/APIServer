"""
Tests for configuration module
"""
import os
import pytest
from core.config import Settings, InMemoryDbSettings, get_settings
from core.db import reset_engine


def test_settings_detection():
    """Test that the correct settings class is used based on environment"""
    # When SETTINGS_MODE is set to test
    os.environ["SETTINGS_MODE"] = "test"
    # Clear any cached settings
    get_settings.cache_clear()
    reset_engine()
    
    settings = get_settings()
    assert isinstance(settings, InMemoryDbSettings)
    assert settings.TESTING is True
    assert settings.SQLALCHEMY_DATABASE_URI == "sqlite:///:memory:"
    
    # When SETTINGS_MODE is not test
    os.environ["SETTINGS_MODE"] = "production"
    # Clear the lru_cache to force re-evaluation
    get_settings.cache_clear()
    reset_engine()
    
    settings = get_settings()
    # Now we need to check if it's not a InMemoryDbSettings instance, rather than checking for TESTING attribute
    assert isinstance(settings, Settings)
    assert not isinstance(settings, InMemoryDbSettings)
    
    # Since the env vars aren't set in the test environment, we can't reliably test
    # the exact URI format, but we can at least check that it comes from the base Settings class
    assert hasattr(settings, "SQLALCHEMY_DATABASE_URI")


def test_test_settings_values(test_settings):
    """Test the TestSettings fixture from conftest.py"""
    assert test_settings.TESTING is True
    assert test_settings.SQLALCHEMY_DATABASE_URI == "sqlite:///:memory:"
    assert test_settings.DB_USER == "test_user"


def test_override_test_settings():
    """Test that we can override InMemoryDbSettings values"""
    os.environ["DB_USER"] = "custom_test_user"
    settings = InMemoryDbSettings()
    assert settings.DB_USER == "custom_test_user"
    
    # Clean up
    os.environ.pop("DB_USER", None)