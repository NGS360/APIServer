"""
Workflow Models
"""
import uuid
from typing import List
from sqlmodel import Field, Relationship, SQLModel


class Attribute(SQLModel):
    key: str | None
    value: str | None


class WorkflowAttribute(SQLModel, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    workflow_id: uuid.UUID = Field(foreign_key="workflow.id")
    key: str
    value: str

    # Add the back-reference relationship
    workflow: "Workflow" = Relationship(back_populates="attributes")


class Workflow(SQLModel, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    name: str
    definition_uri: str
    engine: str
    engine_id: str | None
    engine_version: str | None
    attributes: List[WorkflowAttribute] | None = Relationship(back_populates="workflow")


class WorkflowCreate(SQLModel):
    name: str
    definition_uri: str
    engine: str
    attributes: List[Attribute] | None = None


class WorkflowPublic(SQLModel):
    id: str
    name: str
    engine: str | None
    engine_id: str | None
    attributes: List[Attribute] | None
