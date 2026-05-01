"""
Workflow Models

Workflow — Platform-agnostic workflow identity
WorkflowVersion — Versioned definition of a workflow (holds auto-increment version + definition_uri)
WorkflowVersionAlias — Named pointer (e.g. production, development) to a specific version
WorkflowDeployment — Platform-specific deployment of a workflow version
WorkflowAttribute — Key-value metadata
WorkflowVersionAttribute — Key-value metadata for workflow versions
"""
import uuid
from datetime import datetime, timezone
from typing import List

from sqlmodel import Field, Relationship, SQLModel, UniqueConstraint


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

class Attribute(SQLModel):
    """Reusable key-value pair for request/response payloads."""
    key: str | None
    value: str | None


# ---------------------------------------------------------------------------
# Database tables
# ---------------------------------------------------------------------------

class WorkflowAttribute(SQLModel, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    workflow_id: uuid.UUID = Field(foreign_key="workflow.id")
    key: str
    value: str

    # Relationships
    workflow: "Workflow" = Relationship(back_populates="attributes")


class WorkflowVersionAttribute(SQLModel, table=True):
    """Key-value metadata for workflow versions."""
    __tablename__ = "workflowversionattribute"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    workflow_version_id: uuid.UUID = Field(foreign_key="workflowversion.id")
    key: str
    value: str

    # Relationships
    workflow_version: "WorkflowVersion" = Relationship(back_populates="attributes")


class Workflow(SQLModel, table=True):
    """Platform-agnostic workflow identity."""
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    name: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    created_by: str

    # Relationships
    attributes: List[WorkflowAttribute] | None = Relationship(back_populates="workflow")
    versions: List["WorkflowVersion"] | None = Relationship(back_populates="workflow")
    aliases: List["WorkflowVersionAlias"] | None = Relationship(back_populates="workflow")


class WorkflowVersion(SQLModel, table=True):
    """Versioned definition of a workflow — holds auto-increment version and definition URI."""
    __tablename__ = "workflowversion"
    __table_args__ = (
        UniqueConstraint("workflow_id", "version", name="uq_workflow_version"),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    workflow_id: uuid.UUID = Field(foreign_key="workflow.id")
    version: int
    definition_uri: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    created_by: str

    # Relationships
    workflow: Workflow = Relationship(back_populates="versions")
    attributes: List[WorkflowVersionAttribute] | None = Relationship(
        back_populates="workflow_version",
    )
    deployments: List["WorkflowDeployment"] | None = Relationship(
        back_populates="workflow_version",
    )


class WorkflowVersionAlias(SQLModel, table=True):
    """Named pointer to a specific workflow version (e.g. production, development)."""
    __tablename__ = "workflowversionalias"
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
    workflow: Workflow = Relationship(back_populates="aliases")
    workflow_version: WorkflowVersion = Relationship()


class WorkflowDeployment(SQLModel, table=True):
    """Platform-specific deployment of a workflow version (e.g., on Arvados or SevenBridges)."""
    __tablename__ = "workflowdeployment"
    __table_args__ = (
        UniqueConstraint("workflow_version_id", "engine", name="uq_workflowversion_engine"),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    workflow_version_id: uuid.UUID = Field(foreign_key="workflowversion.id")
    engine: str = Field(foreign_key="platform.name")
    external_id: str  # Workflow identifier on the external platform
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    created_by: str

    # Relationships
    workflow_version: WorkflowVersion = Relationship(back_populates="deployments")


# ---------------------------------------------------------------------------
# Request / Response models — Workflow
# ---------------------------------------------------------------------------

class WorkflowCreate(SQLModel):
    name: str
    attributes: List[Attribute] | None = None


class WorkflowVersionSummary(SQLModel):
    """Lightweight version reference for inclusion in workflow responses."""
    id: uuid.UUID
    version: int
    definition_uri: str
    created_at: datetime


class WorkflowAliasSummary(SQLModel):
    """Alias info included in workflow responses."""
    alias: str
    workflow_version_id: uuid.UUID
    version: int  # Resolved version number for convenience


class WorkflowPublic(SQLModel):
    id: uuid.UUID
    name: str
    created_at: datetime
    created_by: str
    attributes: List[Attribute] | None = None
    versions: List[WorkflowVersionSummary] | None = None
    aliases: List[WorkflowAliasSummary] | None = None


# ---------------------------------------------------------------------------
# Request / Response models — WorkflowVersion
# ---------------------------------------------------------------------------

class WorkflowVersionCreate(SQLModel):
    definition_uri: str


class WorkflowVersionPublic(SQLModel):
    id: uuid.UUID
    workflow_id: uuid.UUID
    version: int
    definition_uri: str
    created_at: datetime
    created_by: str
    deployments: List["WorkflowDeploymentPublic"] | None = None


# ---------------------------------------------------------------------------
# Request / Response models — WorkflowVersionAlias
# ---------------------------------------------------------------------------

class WorkflowVersionAliasSet(SQLModel):
    """Body for PUT /workflows/{id}/aliases/{alias}."""
    workflow_version_id: uuid.UUID


class WorkflowVersionAliasPublic(SQLModel):
    id: uuid.UUID
    workflow_id: uuid.UUID
    alias: str
    workflow_version_id: uuid.UUID
    version: int  # Resolved version number
    created_at: datetime
    created_by: str


# ---------------------------------------------------------------------------
# Request / Response models — WorkflowDeployment
# ---------------------------------------------------------------------------

class WorkflowDeploymentCreate(SQLModel):
    engine: str
    external_id: str


class WorkflowDeploymentPublic(SQLModel):
    id: uuid.UUID
    workflow_version_id: uuid.UUID
    engine: str
    external_id: str
    created_at: datetime
    created_by: str
