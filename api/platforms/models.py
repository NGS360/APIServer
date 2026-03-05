"""
Models for the Platforms API

Platform — a registered workflow execution engine (e.g., Arvados, SevenBridges).
Single-column table: name is the PK.
"""

from sqlmodel import SQLModel, Field


class Platform(SQLModel, table=True):
    """Workflow execution platform (e.g., Arvados, SevenBridges)."""
    name: str = Field(primary_key=True)


class PlatformCreate(SQLModel):
    name: str


class PlatformPublic(SQLModel):
    name: str
