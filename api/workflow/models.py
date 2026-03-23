"""
Workflow Models

Workflow — Platform-agnostic workflow identity
WorkflowVersion — Versioned definition of a workflow (holds version + definition_uri)
WorkflowVersionAlias — Named pointer (production/development) to a specific version
WorkflowRegistration — Platform-specific registration of a workflow version
WorkflowRun — Execution record of a workflow version on a specific platform
WorkflowAttribute / WorkflowRunAttribute — Key-value metadata
"""
import enum
import uuid
from datetime import datetime, timezone
from typing import List

from sqlmodel import Field, Relationship, SQLModel, UniqueConstraint


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class VersionAlias(str, enum.Enum):
    """Fixed set of alias labels for workflow versions."""
    production = "production"
    development = "development"


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
    """Versioned definition of a workflow — holds version string and definition URI."""
    __tablename__ = "workflowversion"
    __table_args__ = (
        UniqueConstraint("workflow_id", "version", name="uq_workflow_version"),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    workflow_id: uuid.UUID = Field(foreign_key="workflow.id")
    version: str
    definition_uri: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    created_by: str

    # Relationships
    workflow: Workflow = Relationship(back_populates="versions")
    registrations: List["WorkflowRegistration"] | None = Relationship(
        back_populates="workflow_version",
    )
    runs: List["WorkflowRun"] | None = Relationship(back_populates="workflow_version")


class WorkflowVersionAlias(SQLModel, table=True):
    """Named pointer to a specific workflow version (e.g. production, development)."""
    __tablename__ = "workflowversionalias"
    __table_args__ = (
        UniqueConstraint("workflow_id", "alias", name="uq_workflow_alias"),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    workflow_id: uuid.UUID = Field(foreign_key="workflow.id")
    alias: VersionAlias
    workflow_version_id: uuid.UUID = Field(foreign_key="workflowversion.id")
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    created_by: str

    # Relationships
    workflow: Workflow = Relationship(back_populates="aliases")
    workflow_version: WorkflowVersion = Relationship()


class WorkflowRegistration(SQLModel, table=True):
    """Platform-specific registration of a workflow version (e.g., on Arvados or SevenBridges)."""
    __tablename__ = "workflowregistration"
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
    workflow_version: WorkflowVersion = Relationship(back_populates="registrations")


class WorkflowRunAttribute(SQLModel, table=True):
    """Key-value metadata for a workflow run."""
    __tablename__ = "workflowrunattribute"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    workflow_run_id: uuid.UUID = Field(foreign_key="workflowrun.id")
    key: str
    value: str

    # Relationships
    workflow_run: "WorkflowRun" = Relationship(back_populates="attributes")


class WorkflowRun(SQLModel, table=True):
    """Provenance record — links a workflow version to an external execution."""
    __tablename__ = "workflowrun"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    workflow_version_id: uuid.UUID = Field(foreign_key="workflowversion.id")
    engine: str = Field(foreign_key="platform.name")
    external_run_id: str  # External run/job ID on the platform (required)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    created_by: str

    # Relationships
    workflow_version: WorkflowVersion = Relationship(back_populates="runs")
    attributes: List[WorkflowRunAttribute] | None = Relationship(back_populates="workflow_run")


# ---------------------------------------------------------------------------
# Request / Response models — Workflow
# ---------------------------------------------------------------------------

class WorkflowCreate(SQLModel):
    name: str
    attributes: List[Attribute] | None = None


class WorkflowVersionSummary(SQLModel):
    """Lightweight version reference for inclusion in workflow responses."""
    id: uuid.UUID
    version: str
    definition_uri: str
    created_at: datetime


class WorkflowAliasSummary(SQLModel):
    """Alias info included in workflow responses."""
    alias: VersionAlias
    workflow_version_id: uuid.UUID
    version: str  # Resolved version string for convenience


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
    version: str
    definition_uri: str


class WorkflowVersionPublic(SQLModel):
    id: uuid.UUID
    workflow_id: uuid.UUID
    version: str
    definition_uri: str
    created_at: datetime
    created_by: str
    registrations: List["WorkflowRegistrationPublic"] | None = None


# ---------------------------------------------------------------------------
# Request / Response models — WorkflowVersionAlias
# ---------------------------------------------------------------------------

class WorkflowVersionAliasSet(SQLModel):
    """Body for PUT /workflows/{id}/aliases/{alias}."""
    workflow_version_id: uuid.UUID


class WorkflowVersionAliasPublic(SQLModel):
    id: uuid.UUID
    workflow_id: uuid.UUID
    alias: VersionAlias
    workflow_version_id: uuid.UUID
    version: str  # Resolved version string
    created_at: datetime
    created_by: str


# ---------------------------------------------------------------------------
# Request / Response models — WorkflowRegistration
# ---------------------------------------------------------------------------

class WorkflowRegistrationCreate(SQLModel):
    engine: str
    external_id: str


class WorkflowRegistrationPublic(SQLModel):
    id: uuid.UUID
    workflow_version_id: uuid.UUID
    engine: str
    external_id: str
    created_at: datetime
    created_by: str


# ---------------------------------------------------------------------------
# Request / Response models — WorkflowRun
# ---------------------------------------------------------------------------

class WorkflowRunCreate(SQLModel):
    workflow_version_id: uuid.UUID
    engine: str
    external_run_id: str
    attributes: List[Attribute] | None = None


class WorkflowRunPublic(SQLModel):
    id: uuid.UUID
    workflow_version_id: uuid.UUID
    workflow_name: str | None = None
    workflow_version: str | None = None
    engine: str
    external_run_id: str
    created_at: datetime
    created_by: str
    attributes: List[Attribute] | None = None


class WorkflowRunsPublic(SQLModel):
    """Paginated list of workflow runs."""
    data: List[WorkflowRunPublic]
    total_items: int
    total_pages: int
    current_page: int
    per_page: int
    has_next: bool
    has_prev: bool
