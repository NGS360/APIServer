"""
Application Configuration
Add constants, secrets, env variables here
"""
from functools import lru_cache
import os
from urllib.parse import urlparse, urlunparse, quote
from pydantic import computed_field
from pydantic_settings import BaseSettings, SettingsConfigDict

# Define settings class for univeral access
class Settings(BaseSettings):
    # Computed or constant values
    client_origin: str | None = os.getenv("client_origin")

    # SQLAlchemy - Create db connection string
    SQLALCHEMY_DATABASE_URI: str = os.getenv("SQLALCHEMY_DATABASE_URI", "sqlite://")
    @computed_field
    @property
    def SQLALCHEMY_DATABASE_URI_MASKED_PASSWORD(self) -> str:
        """
        def mask_password_in_uri(uri: str, mask: str = "*****") -> str:

        Mask the password in a SQLAlchemy database URI.

        Args:
            uri (str): The database URI (e.g. "postgresql://user:password@host/dbname").
            mask (str): The string to replace the password with.

        Returns:
            str: The URI with the password masked.
        """
        uri = self.SQLALCHEMY_DATABASE_URI
        mask = "*****"

        parsed = urlparse(uri)

        if parsed.password is None:
            return uri  # Nothing to mask

        # Rebuild the netloc with the password masked
        userinfo = parsed.username or ''
        if userinfo:
            userinfo += f":{mask}"
        netloc = f"{userinfo}@{parsed.hostname}"
        if parsed.port:
            netloc += f":{parsed.port}"

        # Rebuild the full URI with masked password
        masked = parsed._replace(netloc=netloc)
        return urlunparse(masked)

    # ElasticSearch Configuration
    ELASTICSEARCH_URL: str | None = os.getenv("ELASTICSEARCH_URL")
    ELASTICSEARCH_USER: str | None = os.getenv("ELASTICSEARCH_USER")
    ELASTICSEARCH_PASSWORD: str | None = os.getenv("ELASTICSEARCH_PASSWORD")

    # Read environment variables from .env file, if it exists
    model_config = SettingsConfigDict(env_file=".env")


# Export settings
@lru_cache
def get_settings() -> Settings:
    """
    Get settings instance, cached for performance
    """
    return Settings()

if __name__ == '__main__':
    # To use in other modules
    # from core.config import get_settings
    print(get_settings().SQLALCHEMY_DATABASE_URI)
