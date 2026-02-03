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
        # Use cached secret if available
        if self._secret_cache is None:
            env_secret = os.getenv('ENV_SECRETS')
            if env_secret:
                self._secret_cache = get_secret(env_secret,
                                                os.getenv("AWS_REGION",
                                                          'us-east-1'))
        if self._secret_cache:
            secret_value = self._secret_cache.get(env_var_name)
            if secret_value is not None:
                return secret_value

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

    @computed_field
    @property
    def OPENSEARCH_USE_SSL(self) -> bool:
        """Get OpenSearch use SSL flag from env or secrets"""
        value = self._get_config_value("OPENSEARCH_USE_SSL", default="true")
        return value.lower() in ("true", "1", "yes")

    @computed_field
    @property
    def OPENSEARCH_VERIFY_CERTS(self) -> bool:
        """Get OpenSearch certificate verification setting from env or secrets (defaults to False)"""
        value = self._get_config_value("OPENSEARCH_VERIFY_CERTS", default="false")
        return value.lower() in ("true", "1", "yes")

    # AWS Configuration
    @computed_field
    @property
    def AWS_ACCESS_KEY_ID(self) -> str | None:
        """Get AWS Access Key ID from env or secrets"""
        return self._get_config_value("AWS_ACCESS_KEY_ID")

    @computed_field
    @property
    def AWS_SECRET_ACCESS_KEY(self) -> str | None:
        """Get AWS Secret Access Key from env or secrets"""
        return self._get_config_value("AWS_SECRET_ACCESS_KEY")

    @computed_field
    @property
    def AWS_REGION(self) -> str:
        """Get AWS Region from env or secrets (defaults to us-east-1)"""
        return self._get_config_value("AWS_REGION", default="us-east-1")

    # Options are from api.files.models.StorageBackend
    STORAGE_BACKEND: str = os.getenv("STORAGE_BACKEND", "s3")
    STORAGE_ROOT_PATH: str = os.getenv("STORAGE_URI", "s3://my-storage-bucket")

    # JWT Configuration
    @computed_field
    @property
    def JWT_SECRET_KEY(self) -> str:
        """Get JWT secret key from env or secrets"""
        return self._get_config_value(
            "JWT_SECRET_KEY",
            default="change-this-secret-key-in-production"
        )

    @computed_field
    @property
    def JWT_ALGORITHM(self) -> str:
        """Get JWT algorithm from env or secrets"""
        return self._get_config_value("JWT_ALGORITHM", default="HS256")

    @computed_field
    @property
    def ACCESS_TOKEN_EXPIRE_MINUTES(self) -> int:
        """Get access token expiration in minutes"""
        value = self._get_config_value("ACCESS_TOKEN_EXPIRE_MINUTES", default="30")
        return int(value)

    @computed_field
    @property
    def REFRESH_TOKEN_EXPIRE_DAYS(self) -> int:
        """Get refresh token expiration in days"""
        value = self._get_config_value("REFRESH_TOKEN_EXPIRE_DAYS", default="30")
        return int(value)

    # Password Policy
    @computed_field
    @property
    def PASSWORD_MIN_LENGTH(self) -> int:
        """Get minimum password length"""
        value = self._get_config_value("PASSWORD_MIN_LENGTH", default="8")
        return int(value)

    @computed_field
    @property
    def PASSWORD_REQUIRE_UPPERCASE(self) -> bool:
        """Check if password requires uppercase"""
        value = self._get_config_value("PASSWORD_REQUIRE_UPPERCASE", default="true")
        return value.lower() in ("true", "1", "yes")

    @computed_field
    @property
    def PASSWORD_REQUIRE_LOWERCASE(self) -> bool:
        """Check if password requires lowercase"""
        value = self._get_config_value("PASSWORD_REQUIRE_LOWERCASE", default="true")
        return value.lower() in ("true", "1", "yes")

    @computed_field
    @property
    def PASSWORD_REQUIRE_DIGIT(self) -> bool:
        """Check if password requires digit"""
        value = self._get_config_value("PASSWORD_REQUIRE_DIGIT", default="true")
        return value.lower() in ("true", "1", "yes")

    @computed_field
    @property
    def PASSWORD_REQUIRE_SPECIAL(self) -> bool:
        """Check if password requires special character"""
        value = self._get_config_value("PASSWORD_REQUIRE_SPECIAL", default="false")
        return value.lower() in ("true", "1", "yes")

    # Account Lockout
    @computed_field
    @property
    def MAX_FAILED_LOGIN_ATTEMPTS(self) -> int:
        """Get max failed login attempts before lockout"""
        value = self._get_config_value("MAX_FAILED_LOGIN_ATTEMPTS", default="5")
        return int(value)

    @computed_field
    @property
    def ACCOUNT_LOCKOUT_DURATION_MINUTES(self) -> int:
        """Get account lockout duration in minutes"""
        value = self._get_config_value("ACCOUNT_LOCKOUT_DURATION_MINUTES", default="30")
        return int(value)

    # Email Configuration
    @computed_field
    @property
    def EMAIL_ENABLED(self) -> bool:
        """Check if email is enabled"""
        value = self._get_config_value("EMAIL_ENABLED", default="false")
        return value.lower() in ("true", "1", "yes")

    @computed_field
    @property
    def FROM_EMAIL(self) -> str:
        """Get from email address"""
        return self._get_config_value("FROM_EMAIL", default="noreply@example.com")

    @computed_field
    @property
    def FROM_NAME(self) -> str:
        """Get from name"""
        return self._get_config_value("FROM_NAME", default="NGS360")

    @computed_field
    @property
    def FRONTEND_URL(self) -> str:
        """Get frontend URL"""
        return self._get_config_value("FRONTEND_URL", default="http://localhost:3000")

    @computed_field
    @property
    def MAIL_SERVER(self) -> str | None:
        """Get mail server"""
        return self._get_config_value("MAIL_SERVER")

    @computed_field
    @property
    def MAIL_PORT(self) -> str | None:
        """Get mail server port"""
        return self._get_config_value("MAIL_PORT")

    @computed_field
    @property
    def MAIL_USERNAME(self) -> str | None:
        """Get mail username"""
        return self._get_config_value("MAIL_USERNAME")

    @computed_field
    @property
    def MAIL_PASSWORD(self) -> str | None:
        """Get mail password"""
        return self._get_config_value("MAIL_PASSWORD")

    @computed_field
    @property
    def MAIL_USE_TLS(self) -> bool:
        """Check if mail uses TLS"""
        value = self._get_config_value("MAIL_USE_TLS", default="false")
        return value.lower() in ("true", "1", "yes")

    @computed_field
    @property
    def MAIL_ADMINS(self) -> str | None:
        """Get mail admins"""
        return self._get_config_value("MAIL_ADMINS")

    # OAuth2 Configuration
    @computed_field
    @property
    def OAUTH_GOOGLE_CLIENT_ID(self) -> str | None:
        """Get Google OAuth client ID"""
        return self._get_config_value("OAUTH_GOOGLE_CLIENT_ID")

    @computed_field
    @property
    def OAUTH_GOOGLE_CLIENT_SECRET(self) -> str | None:
        """Get Google OAuth client secret"""
        return self._get_config_value("OAUTH_GOOGLE_CLIENT_SECRET")

    @computed_field
    @property
    def OAUTH_GITHUB_CLIENT_ID(self) -> str | None:
        """Get GitHub OAuth client ID"""
        return self._get_config_value("OAUTH_GITHUB_CLIENT_ID")

    @computed_field
    @property
    def OAUTH_GITHUB_CLIENT_SECRET(self) -> str | None:
        """Get GitHub OAuth client secret"""
        return self._get_config_value("OAUTH_GITHUB_CLIENT_SECRET")

    @computed_field
    @property
    def OAUTH_MICROSOFT_CLIENT_ID(self) -> str | None:
        """Get Microsoft OAuth client ID"""
        return self._get_config_value("OAUTH_MICROSOFT_CLIENT_ID")

    @computed_field
    @property
    def OAUTH_MICROSOFT_CLIENT_SECRET(self) -> str | None:
        """Get Microsoft OAuth client secret"""
        return self._get_config_value("OAUTH_MICROSOFT_CLIENT_SECRET")

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
