"""
Models for the Platforms API

Platform — a registered workflow execution engine (e.g., Arvados, SevenBridges).
UUID primary key with a unique constraint on name.
"""

import uuid

from sqlmodel import SQLModel, Field


class Platform(SQLModel, table=True):
    """Workflow execution platform (e.g., Arvados, SevenBridges)."""
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    name: str = Field(unique=True)


class PlatformCreate(SQLModel):
    name: str


class PlatformPublic(SQLModel):
    id: uuid.UUID
    name: str
