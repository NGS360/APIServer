"""
Application Configuration
Add constants, secrets, env variables here
"""
from functools import lru_cache
import os
from typing import Literal
from pydantic import computed_field
from pydantic_settings import BaseSettings, SettingsConfigDict

# Define settings class for univeral access
class Settings(BaseSettings):
    # Computed or constant values
    client_origin: str | None = os.getenv("client_origin")
    DB_SERVER: str | None = os.getenv("DB_SERVER")
    DB_PORT: str | None = os.getenv("DB_PORT")
    DB_PASSWORD: str | None = os.getenv("DB_PASSWORD")
    DB_USER: str | None = os.getenv("DB_USER")
    DB_NAME: str | None = os.getenv("DB_NAME")

    # Read environment variables from .env file, if it exists
    model_config = SettingsConfigDict(env_file=".env")

    # SQLAlchemy - Create db connection string
    @computed_field
    @property
    def SQLALCHEMY_DATABASE_URI(self) -> str:
        return f"mysql+pymysql://{self.DB_USER}:{self.DB_PASSWORD}@{self.DB_SERVER}:{self.DB_PORT}/{self.DB_NAME}"

    # SQLAlchemy - Create db connection string
    @computed_field
    @property
    def SQLALCHEMY_DATABASE_URI_MASKED_PASSWORD(self) -> str:
        return f"mysql+pymysql://{self.DB_USER}:*****@{self.DB_SERVER}:{self.DB_PORT}/{self.DB_NAME}"

# Settings for unit tests
class InMemoryDbSettings(Settings):
    """
    Test-specific settings that override the base settings.
    Used primarily for unit tests with in-memory SQLite database.
    """
    # Override database settings
    DB_SERVER: str = "localhost"
    DB_PORT: str = "3306"  # Not used for SQLite but kept for compatibility
    DB_USER: str = "test_user"
    DB_PASSWORD: str = "test_password"
    DB_NAME: str = "test_db"
    TESTING: bool = True
    
    # Override computed field for SQLite in-memory database
    @computed_field
    @property
    def SQLALCHEMY_DATABASE_URI(self) -> str:
        return "sqlite:///:memory:"
    
    @computed_field
    @property
    def SQLALCHEMY_DATABASE_URI_MASKED_PASSWORD(self) -> str:
        return "sqlite:///:memory:"

# Export settings
@lru_cache
def get_settings() -> Settings:
    """
    Get settings instance, cached for performance.
    
    Returns:
        Settings: Regular settings for production/development or
                 TestSettings for test environment.
    """
    # Read the environment variable directly each time to pick up changes
    settings_mode = os.getenv("SETTINGS_MODE", "production")
    if settings_mode.lower() == "test":
        return InMemoryDbSettings()
    return Settings()

def get_test_settings() -> InMemoryDbSettings:
    """
    Get test settings instance explicitly.
    Useful when you need to ensure test settings are used.
    """
    return InMemoryDbSettings()

if __name__ == '__main__':
    # To use in other modules
    # from core.config import get_settings
    print(get_settings().SQLALCHEMY_DATABASE_URI)
