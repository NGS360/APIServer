"""
Application Configuration - Bootstrap Only

This module contains ONLY the minimal settings needed to bootstrap the
application (connect to DB, set up logging, configure CORS). All other
runtime configuration lives in the DB-backed `setting` table and is
accessed via `core.app_settings.app_settings`.

Bootstrap env vars:
    - SQLALCHEMY_DATABASE_URI: Database connection string
    - AWS_REGION: AWS region for SDK calls
    - AWS_ACCESS_KEY_ID: AWS credentials
    - AWS_SECRET_ACCESS_KEY: AWS credentials
    - ENV_SECRETS: AWS Secrets Manager secret name
    - LOG_LEVEL: Application log level
    - client_origin: CORS allowed origin
"""

from functools import lru_cache
import os
import json
from pathlib import Path
from pydantic import computed_field, PrivateAttr
from pydantic_settings import BaseSettings, SettingsConfigDict
import boto3
from botocore.exceptions import ClientError
from dotenv import load_dotenv

# Load .env file into os.environ so os.getenv() works correctly
# This must happen before Settings class is instantiated
env_path = Path(__file__).parent.parent / ".env"
if env_path.exists():
    load_dotenv(env_path)


def get_secret(secret_name: str, region_name: str) -> dict | None:
    """
    Retrieve secrets from AWS Secrets Manager

    Args:
        secret_name: Name of the secret in Secrets Manager
        region_name: AWS region where secret is stored

    Returns:
        dict: Parsed secret value or None if secret cannot be retrieved
    """
    session = boto3.session.Session()
    client = session.client(
        service_name='secretsmanager',
        region_name=region_name
    )
    try:
        secret_value_response = client.get_secret_value(
            SecretId=secret_name
        )
    except ClientError:
        return None
    # Parse and return the secret
    secret = secret_value_response['SecretString'].replace('\n', '')
    return json.loads(
        secret
    )


class Settings(BaseSettings):
    """
    Bootstrap configuration - only values needed before the DB is available.

    All other runtime settings are in the DB `setting` table and accessed
    via `core.app_settings.app_settings`.
    """
    # CORS origin for the frontend client
    client_origin: str | None = os.getenv("client_origin")

    # Cache for AWS Secrets Manager to avoid multiple API calls
    _secret_cache: dict | None = PrivateAttr(default=None)

    def _get_config_value(
        self,
        env_var_name: str,
        default: str | None = None
    ) -> str | None:
        """
        Get configuration value from environment variable or
        AWS Secrets Manager (with caching).

        Args:
            env_var_name: Environment variable name to check first
            default: Default value if not found

        Returns:
            Configuration value, or default value if not found
        """
        # 1. Check environment variable first
        env_value = os.getenv(env_var_name)
        if env_value:
            return env_value

        # 2. Try to get from AWS Secrets Manager with caching
        if self._secret_cache is None:
            env_secret = os.getenv('ENV_SECRETS')
            if env_secret:
                self._secret_cache = get_secret(
                    env_secret,
                    os.getenv("AWS_REGION", 'us-east-1')
                )
        if self._secret_cache:
            secret_value = self._secret_cache.get(env_var_name)
            if secret_value is not None:
                return secret_value

        # 3. Return default value if provided
        return default

    @computed_field
    @property
    def LOG_LEVEL(self) -> str:
        """Application log level (defaults to INFO)"""
        return self._get_config_value("LOG_LEVEL", default="INFO")

    @computed_field
    @property
    def SQLALCHEMY_DATABASE_URI(self) -> str:
        """Database connection URI (defaults to local mysql db)"""
        return self._get_config_value(
            "SQLALCHEMY_DATABASE_URI", default="mysql+pymysql://root:password@localhost:3306/db"
        )

    @computed_field
    @property
    def AWS_ACCESS_KEY_ID(self) -> str | None:
        """AWS Access Key ID"""
        return self._get_config_value("AWS_ACCESS_KEY_ID")

    @computed_field
    @property
    def AWS_SECRET_ACCESS_KEY(self) -> str | None:
        """AWS Secret Access Key"""
        return self._get_config_value("AWS_SECRET_ACCESS_KEY")

    @computed_field
    @property
    def AWS_REGION(self) -> str:
        """AWS Region (defaults to us-east-1)"""
        return self._get_config_value("AWS_REGION", default="us-east-1")

    # Read environment variables from .env file, if it exists
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )


# Export settings
@lru_cache
def get_settings() -> Settings:
    """
    Get bootstrap settings instance, cached for performance.

    NOTE: For runtime settings (JWT, OAuth, email, LDAP, etc.),
    use `from core.app_settings import app_settings` instead.
    """
    return Settings()


if __name__ == "__main__":
    print(get_settings().SQLALCHEMY_DATABASE_URI)
