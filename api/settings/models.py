"""
Models for the Settings API
"""

from datetime import datetime
from sqlmodel import SQLModel, Field, Column
from sqlalchemy import JSON, text
from pydantic import ConfigDict


class Setting(SQLModel, table=True):
    """
    Represents an application setting with a fixed key.
    Keys are used as primary identifiers and cannot be changed.
    """
    key: str = Field(primary_key=True, max_length=255)
    value: str = Field(nullable=False)
    name: str = Field(max_length=255, nullable=False)
    description: str | None = Field(default=None)
    tags: list[dict[str, str]] | None = Field(default=None, sa_column=Column(JSON))
    created_at: datetime | None = Field(default=None, sa_column_kwargs={"server_default": text("CURRENT_TIMESTAMP")})
    updated_at: datetime | None = Field(default=None, sa_column_kwargs={"onupdate": text("CURRENT_TIMESTAMP")})

    model_config = ConfigDict(from_attributes=True)


class SettingUpdate(SQLModel):
    """
    Represents the data needed to update a setting.
    Note: key cannot be updated as it's the primary key.
    """
    value: str | None = None
    name: str | None = None
    description: str | None = None
    tags: list[dict[str, str]] | None = None
