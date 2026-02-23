"""
Models for the Sample API
"""

import uuid
from typing import List, TYPE_CHECKING
from sqlmodel import SQLModel, Field, Relationship, UniqueConstraint
from pydantic import ConfigDict

if TYPE_CHECKING:
    from api.project.models import Project
    from api.files.models import FileSample


class Attribute(SQLModel):
    key: str | None
    value: str | None


class SampleAttribute(SQLModel, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    sample_id: uuid.UUID = Field(foreign_key="sample.id")
    key: str
    value: str
    __table_args__ = (UniqueConstraint("sample_id", "key"),)

    sample: "Sample" = Relationship(back_populates="attributes")


class Sample(SQLModel, table=True):
    __searchable__ = ["sample_id"]

    id: uuid.UUID | None = Field(default_factory=uuid.uuid4, primary_key=True)
    sample_id: str
    project_id: str = Field(foreign_key="project.project_id")
    attributes: List[SampleAttribute] | None = Relationship(back_populates="sample")
    project: "Project" = Relationship(back_populates="samples")
    file_samples: List["FileSample"] | None = Relationship(back_populates="sample")

    model_config = ConfigDict(from_attributes=True)

    __table_args__ = (UniqueConstraint("sample_id", "project_id"),)


class SampleCreate(SQLModel):
    sample_id: str
    attributes: List[Attribute] | None = None
    model_config = ConfigDict(extra="forbid")


class SamplePublic(SQLModel):
    sample_id: str
    project_id: str
    attributes: List[Attribute] | None


class SamplesPublic(SQLModel):
    data: List[SamplePublic]
    data_cols: list[str] | None = None
    total_items: int
    total_pages: int
    current_page: int
    per_page: int
    has_next: bool
    has_prev: bool
