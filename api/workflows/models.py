"""
Workflow Models

Workflow — Platform-agnostic workflow identity
"""
import uuid
from datetime import datetime, timezone
from typing import List

from sqlalchemy import JSON, ForeignKeyConstraint
from sqlmodel import Column, Field, SQLModel, Relationship, UniqueConstraint


class WorkflowAttribute(SQLModel, table=True):
    __table_args__ = (
        UniqueConstraint("workflow_id", "key", name="uq_workflow_attribute_key"),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    workflow_id: uuid.UUID = Field(foreign_key="workflow.id")
    key: str
    value: str

    # Relationships
    workflow: "Workflow" = Relationship(back_populates="attributes")


class WorkflowVersionAttribute(SQLModel, table=True):
    __table_args__ = (
        UniqueConstraint(
            "workflowversion_id",
            "key",
            name="uq_workflow_version_attribute_key"
        ),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    workflowversion_id: uuid.UUID = Field(foreign_key="workflowversion.id")
    key: str
    value: str

    # Relationships
    workflowversion: "WorkflowVersion" = Relationship(back_populates="attributes")


class WorkflowVersion(SQLModel, table=True):
    """ Versioned definition of a workflow — holds auto-increment version and definition URI. """
    __table_args__ = (
        UniqueConstraint("workflow_id", "version", name="uq_workflow_version"),
        # Target for the composite FK from WorkflowVersionAlias.
        UniqueConstraint("workflow_id", "id", name="uq_workflow_version_workflow_id"),
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
        back_populates="workflowversion",
    )
    # deployments: List["WorkflowDeployment"] | None = Relationship(
    #    back_populates="workflowversion",
    # )


class WorkflowVersionAlias(SQLModel, table=True):
    """ Named pointer to a specific workflow version (e.g. production, development). """
    __table_args__ = (
        UniqueConstraint("workflow_id", "alias", name="uq_workflow_alias"),
        # The version must belong to the same workflow as the alias.
        ForeignKeyConstraint(
            ["workflow_id", "workflow_version_id"],
            ["workflowversion.workflow_id", "workflowversion.id"],
            name="fk_workflow_alias_version_same_workflow",
        ),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    workflow_id: uuid.UUID = Field(foreign_key="workflow.id")
    workflow_version_id: uuid.UUID
    alias: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    created_by: str = Field(foreign_key="users.username")

    # Relationships
    workflow: "Workflow" = Relationship(back_populates="aliases")
    # Read-only: workflow_id/workflow_version_id are written by the columns, and the
    # composite FK already overlaps the workflow relationship.
    workflow_version: "WorkflowVersion" = Relationship(
        sa_relationship_kwargs={"viewonly": True},
    )


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
