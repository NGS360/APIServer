"""
Models for the Project API
"""

import uuid
from sqlmodel import SQLModel, Field, Relationship, UniqueConstraint
from typing import List, TYPE_CHECKING
from pydantic import ConfigDict

if TYPE_CHECKING:
    from api.samples.models import Sample


class Attribute(SQLModel):
    key: str | None
    value: str | None


class ProjectAttribute(SQLModel, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    project_id: uuid.UUID = Field(foreign_key="project.id", primary_key=True)
    key: str
    value: str

    projects: List["Project"] = Relationship(back_populates="attributes")
    __table_args__ = (UniqueConstraint("project_id", "key"),)


class Project(SQLModel, table=True):
    __searchable__ = ["project_id", "name"]

    id: uuid.UUID | None = Field(default_factory=uuid.uuid4, primary_key=True)
    project_id: str = Field(unique=True)
    name: str | None = Field(max_length=2048)
    attributes: List[ProjectAttribute] | None = Relationship(back_populates="projects")
    samples: List["Sample"] = Relationship(back_populates="project")

    model_config = ConfigDict(from_attributes=True)


class ProjectCreate(SQLModel):
    name: str
    attributes: List[Attribute] | None = None
    model_config = ConfigDict(extra="forbid")


class ProjectPublic(SQLModel):
    project_id: str
    name: str | None
    data_folder_uri: str | None
    results_folder_uri: str | None
    attributes: List[Attribute] | None

class ProjectsPublic(SQLModel):
    data: List[ProjectPublic]
    total_items: int
    total_pages: int
    current_page: int
    per_page: int
    has_next: bool
    has_prev: bool
