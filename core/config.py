"""
Application Configuration
Add constants, secrets, env variables here
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


def get_secret(secret_name: str, region_name: str) -> dict:
    """
    Retrieve secrets from AWS Secrets Manager

    Args:
        secret_name: Name of the secret in Secrets Manager
        region_name: AWS region where secret is stored

    Returns:
        dict: Parsed secret value

    Raises:
        ClientError: If secret cannot be retrieved
    """
    session = boto3.session.Session()
    client = session.client(
        service_name='secretsmanager',
        region_name=region_name
    )
    try:
        get_secret_value_response = client.get_secret_value(
            SecretId=secret_name
        )
    except ClientError:  # as e:
        # Log the error and re-raise
        # print(f"Error retrieving secret {secret_name}: {e}")
        raise
    # Parse and return the secret
    secret = get_secret_value_response['SecretString']
    return json.loads(
        secret.replace('\n', '')
    )


# Define settings class for univeral access
class Settings(BaseSettings):
    # Computed or constant values
    client_origin: str | None = os.getenv("client_origin")

    # Cache for AWS Secrets Manager to avoid multiple API calls
    # Note: Must use PrivateAttr for Pydantic v2 private attributes
    _secret_cache: dict | None = PrivateAttr(default=None)

    def _get_config_value(
        self,
        env_var_name: str,
        secret_key_name: str | None = None,
        default: str | None = None
    ) -> str | None:
        """
        Get configuration value from environment variable or AWS Secrets Manager (with caching).

        Args:
            env_var_name: Environment variable name to check first
            secret_key_name: Key name in AWS Secrets (defaults to env_var_name if not provided)
            default: Default value to return if not found in env or secrets

        Returns:
            Configuration value, or default value if not found
        """
        # 1. Check environment variable first
        env_value = os.getenv(env_var_name)
        if env_value:
            return env_value

        # 2. Try to get from AWS Secrets Manager with caching
        if secret_key_name is None:
            secret_key_name = env_var_name

        try:
            # Use cached secret if available
            if self._secret_cache is None:
                env_secret = os.getenv('ENV_SECRETS')
                self._secret_cache = get_secret(env_secret, os.getenv("AWS_REGION", 'us-east-1'))

            secret_value = self._secret_cache.get(secret_key_name)
            if secret_value is not None:
                return secret_value
        except Exception:
            pass

        # 3. Return default value if provided
        return default

    # SQLAlchemy - Create db connection string
    @computed_field
    @property
    def SQLALCHEMY_DATABASE_URI(self) -> str:
        """Build database URI from env or secrets, defaults to sqlite://"""
        return self._get_config_value("SQLALCHEMY_DATABASE_URI", default="sqlite://")

    # ElasticSearch Configuration
    @computed_field
    @property
    def OPENSEARCH_HOST(self) -> str | None:
        """Get OpenSearch host from env or secrets"""
        return self._get_config_value("OPENSEARCH_HOST")

    @computed_field
    @property
    def OPENSEARCH_PORT(self) -> str | None:
        """Get OpenSearch post from env or secrets"""
        return self._get_config_value("OPENSEARCH_PORT")

    @computed_field
    @property
    def OPENSEARCH_USER(self) -> str | None:
        """Get OpenSearch user from env or secrets"""
        return self._get_config_value("OPENSEARCH_USER")

    @computed_field
    @property
    def OPENSEARCH_PASSWORD(self) -> str | None:
        """Get OpenSearch password from env or secrets"""
        # Note: Secret key is 'OPENSEARCH_PASS' not 'OPENSEARCH_PASSWORD'
        return self._get_config_value("OPENSEARCH_PASSWORD")

    # AWS Credentials
    AWS_ACCESS_KEY_ID: str | None = os.getenv("AWS_ACCESS_KEY_ID")
    AWS_SECRET_ACCESS_KEY: str | None = os.getenv("AWS_SECRET_ACCESS_KEY")
    AWS_REGION: str | None = os.getenv("AWS_REGION")

    # Bucket configurations
    VITE_DATA_BUCKET_URI: str = os.getenv("VITE_DATA_BUCKET_URI", "s3://my-data-bucket/")
    VITE_RESULTS_BUCKET_URI: str = os.getenv("VITE_RESULTS_BUCKET_URI", "s3://my-results-bucket/")

    # Read environment variables from .env file, if it exists
    # extra='ignore' prevents validation errors from extra env vars
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
    Get settings instance, cached for performance
    """
    return Settings()


if __name__ == "__main__":
    # To use in other modules
    # from core.config import get_settings
    print(get_settings().SQLALCHEMY_DATABASE_URI)
