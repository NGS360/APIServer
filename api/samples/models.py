"""
Models for the Sample API
"""
import uuid
from sqlmodel import SQLModel, Field, Relationship, UniqueConstraint
from typing import List
from pydantic import ConfigDict
from api.project.models import Project

class Attribute (SQLModel):
  key: str | None
  value: str | None

class SampleAttribute(SQLModel, table=True):
  id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
  sample_id: uuid.UUID = Field(foreign_key="sample.id", primary_key=True)
  key: str
  value: str
  __table_args__ = (UniqueConstraint("sample_id", "key"),)
  
  sample: "Sample" = Relationship(back_populates="attributes")

class Sample(SQLModel, table=True):
  id: uuid.UUID | None = Field(default_factory=uuid.uuid4, primary_key=True)
  sample_id: str
  project_id: uuid.UUID = Field(foreign_key="project.id")
  project: Project = Relationship(back_populates="samples")
  attributes: List[SampleAttribute] | None = Relationship(
    back_populates="sample"
  )
  model_config = ConfigDict(from_attributes=True)
  
  __table_args__ = (UniqueConstraint("sample_id", "project_id"),)

class SampleCreate(SQLModel):
  sample_id: str
  project_id: uuid.UUID
  name: str
  attributes: List[Attribute] | None = None

class SamplePublic(SQLModel):
  sample_id: str
  project_id: uuid.UUID
  name: str | None
  attributes: List[Attribute] | None

class SamplesPublic(SQLModel):
  data: List[SamplePublic]
  total_items: int
  total_pages: int
  current_page: int
  per_page: int
  has_next: bool
  has_prev: bool
