"""
Application Configuration
Add constants, secrets, env variables here
"""
import os
from pydantic import computed_field
from pydantic_settings import BaseSettings

# Define settings class for univeral access
class Settings(BaseSettings):
    # Computed or constant values
    client_origin: str | None = os.getenv("client_origin")
    DB_SERVER: str | None = os.getenv("DB_SERVER")
    DB_PORT: str | None = os.getenv("DB_PORT")
    DB_PASSWORD: str | None = os.getenv("DB_PASSWORD")
    DB_USER: str | None = os.getenv("DB_USER")
    DB_NAME: str | None = os.getenv("DB_NAME")

    # SQLAlchemy - Create db connection string
    @computed_field
    @property
    def SQLALCHEMY_DATABASE_URI(self) -> str:
        return f"mysql+pymysql://{self.DB_USER}:{self.DB_PASSWORD}@{self.DB_SERVER}:{self.DB_PORT}/{self.DB_NAME}"

# Export settings
settings = Settings()

if __name__ == '__main__':
    # To use in other modules
    # from core.config import settings
    print(settings.SQLALCHEMY_DATABASE_URI)