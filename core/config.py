"""
Application Configuration
Add constants, secrets, env variables here
"""

from functools import lru_cache
import os
import json
from urllib.parse import urlparse, urlunparse
from pydantic import computed_field
from pydantic_settings import BaseSettings, SettingsConfigDict
import boto3
from botocore.exceptions import ClientError


def get_secret(secret_name: str, region_name: str) -> dict:
    """
    Retrieve secret from AWS Secrets Manager

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
    except ClientError as e:
        # Log the error and re-raise
        print(f"Error retrieving secret {secret_name}: {e}")
        raise

    # Parse and return the secret
    secret = get_secret_value_response['SecretString']
    return json.loads(secret)


# Define settings class for univeral access
class Settings(BaseSettings):
    # Computed or constant values
    client_origin: str | None = os.getenv("client_origin")

    # SQLAlchemy - Create db connection string
    @computed_field
    @property
    def SQLALCHEMY_DATABASE_URI(self) -> str:
        """Build database URI from secret"""
        # 1. Return the db credentials if available as environment variable
        env_uri = os.getenv("SQLALCHEMY_DATABASE_URI")
        if env_uri:
            return env_uri
        # 2. Read db credentials from AWS Secrets
        try:
            db_secret = os.getenv('DB_SECRET_NAME')
            secret = get_secret(db_secret, os.getenv("AWS_REGION", 'us-east-1'))
            return secret['SQLALCHEMY_DATABASE_URI']
        except Exception as e:
            print(f"Failed to retrieve database credentials: {e}")
            # 3. Fall back to sqllite in-memory
            return "sqlite://"

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
        userinfo = parsed.username or ""
        if userinfo:
            userinfo += f":{mask}"
        netloc = f"{userinfo}@{parsed.hostname}"
        if parsed.port:
            netloc += f":{parsed.port}"

        # Rebuild the full URI with masked password
        masked = parsed._replace(netloc=netloc)
        return urlunparse(masked)

    # ElasticSearch Configuration
    OPENSEARCH_HOST: str | None = os.getenv("OPENSEARCH_HOST")
    OPENSEARCH_PORT: str | None = os.getenv("OPENSEARCH_PORT")
    OPENSEARCH_USER: str | None = os.getenv("OPENSEARCH_USER")
    OPENSEARCH_PASSWORD: str | None = os.getenv("OPENSEARCH_PASSWORD")

    # AWS Credentials
    AWS_ACCESS_KEY_ID: str | None = os.getenv("AWS_ACCESS_KEY_ID")
    AWS_SECRET_ACCESS_KEY: str | None = os.getenv("AWS_SECRET_ACCESS_KEY")
    AWS_REGION: str | None = os.getenv("AWS_REGION")

    # Bucket configurations
    VITE_DATA_BUCKET_URI: str = os.getenv("VITE_DATA_BUCKET_URI", "s3://my-data-bucket/")
    VITE_RESULTS_BUCKET_URI: str = os.getenv("VITE_RESULTS_BUCKET_URI", "s3://my-results-bucket/")

    # Read environment variables from .env file, if it exists
    model_config = SettingsConfigDict(env_file=".env")


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
