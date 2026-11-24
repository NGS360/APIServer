"""
Workflow Models

Workflow — Platform-agnostic workflow identity
"""
import uuid
from datetime import datetime, timezone
from typing import List

from sqlalchemy import JSON
from sqlmodel import Column, Field, SQLModel, Relationship, UniqueConstraint


class WorkflowAttribute(SQLModel, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    workflow_id: uuid.UUID = Field(foreign_key="workflow.id")
    key: str
    value: str

    # Relationships
    workflow: "Workflow" = Relationship(back_populates="attributes")


class WorkflowVersionAttribute(SQLModel, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    workflow_version_id: uuid.UUID = Field(foreign_key="workflowversion.id")
    key: str
    value: str

    # Relationships
    workflow_version: "WorkflowVersion" = Relationship(back_populates="attributes")


class WorkflowVersion(SQLModel, table=True):
    """ Versioned definition of a workflow — holds auto-increment version and definition URI. """
    __table_args__ = (
        UniqueConstraint("workflow_id", "version", name="uq_workflow_version"),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    workflow_id: uuid.UUID = Field(foreign_key="workflow.id")
    version: int
    definition_uri: str
    body: bytes

    inputs: list[dict] | None = Field(default=None, sa_column=Column(JSON))
    outputs: list[dict] | None = Field(default=None, sa_column=Column(JSON))

    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    created_by: str = Field(foreign_key="users.username")

    # Relationships
    workflow: "Workflow" = Relationship(back_populates="versions")
    attributes: List["WorkflowVersionAttribute"] | None = Relationship(
        back_populates="workflow_version",
    )
    # deployments: List["WorkflowDeployment"] | None = Relationship(
    #    back_populates="workflow_version",
    # )


class WorkflowVersionAlias(SQLModel, table=True):
    """ Named pointer to a specific workflow version (e.g. production, development). """
    __table_args__ = (
        UniqueConstraint("workflow_id", "alias", name="uq_workflow_alias"),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    workflow_id: uuid.UUID = Field(foreign_key="workflow.id")
    alias: str
    workflow_version_id: uuid.UUID = Field(foreign_key="workflowversion.id")
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    created_by: str

    # Relationships
    workflow: "Workflow" = Relationship(back_populates="aliases")
    workflow_version: WorkflowVersion = Relationship()


class Workflow(SQLModel, table=True):
    """ Workflow Table """
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    name: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    created_by: str = Field(foreign_key="users.username")

    # Relationships
    attributes: List["WorkflowAttribute"] | None = Relationship(back_populates="workflow")
    versions: List["WorkflowVersion"] | None = Relationship(back_populates="workflow")
    aliases: List["WorkflowVersionAlias"] | None = Relationship(back_populates="workflow")
