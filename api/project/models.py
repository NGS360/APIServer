"""
Models for the Project API
"""
import uuid
from sqlmodel import SQLModel, Field, Relationship, UniqueConstraint
from typing import List
from pydantic import ConfigDict

class Attribute (SQLModel):
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
  id: uuid.UUID | None = Field(default_factory=uuid.uuid4, primary_key=True)
  project_id: str = Field(unique=True)
  name: str | None = Field(max_length=2048)
  attributes: List[ProjectAttribute] | None = Relationship(
    back_populates="projects"
  )
  #samples: List["Sample"] = Relationship(back_populates="project")

  #class Config:
  #  from_attributes=True # will eagerly load relationships (i.e., attributes)
  model_config = ConfigDict(from_attributes=True)
  
class ProjectCreate(SQLModel):
  name: str
  attributes: List[Attribute] | None = None

class ProjectPublic(SQLModel):
  project_id: str
  name: str | None
  attributes: List[Attribute] | None

class ProjectsPublic(SQLModel):
  data: List[ProjectPublic]
  total_items: int
  total_pages: int
  current_page: int
  per_page: int
  has_next: bool
  has_prev: bool