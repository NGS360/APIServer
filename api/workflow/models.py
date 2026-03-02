"""
Workflow Models

Workflow — Platform-agnostic workflow definition
WorkflowRegistration — Platform-specific registration of a workflow
WorkflowRun — Execution record of a workflow on a specific platform
WorkflowAttribute / WorkflowRunAttribute — Key-value metadata
"""
import uuid
from datetime import datetime, timezone
from enum import Enum
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


class Workflow(SQLModel, table=True):
    """Platform-agnostic workflow definition."""
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    name: str
    version: str | None = Field(default=None)
    definition_uri: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    created_by: str

    # Relationships
    attributes: List[WorkflowAttribute] | None = Relationship(back_populates="workflow")
    registrations: List["WorkflowRegistration"] | None = Relationship(back_populates="workflow")
    runs: List["WorkflowRun"] | None = Relationship(back_populates="workflow")


class WorkflowRegistration(SQLModel, table=True):
    """Platform-specific registration of a workflow (e.g., on Arvados or SevenBridges)."""
    __tablename__ = "workflowregistration"
    __table_args__ = (
        UniqueConstraint("workflow_id", "engine", name="uq_workflow_engine"),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    workflow_id: uuid.UUID = Field(foreign_key="workflow.id")
    engine: str
    external_id: str  # Workflow identifier on the external platform
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    created_by: str

    # Relationships
    workflow: Workflow = Relationship(back_populates="registrations")


class WorkflowRunStatus(str, Enum):
    """Status of a workflow execution."""
    PENDING = "Pending"
    RUNNING = "Running"
    SUCCEEDED = "Succeeded"
    FAILED = "Failed"
    CANCELLED = "Cancelled"


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
    """Execution record of a workflow on a specific platform."""
    __tablename__ = "workflowrun"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    workflow_id: uuid.UUID = Field(foreign_key="workflow.id")
    engine: str                                          # Which platform executed this run
    engine_run_id: str | None = Field(default=None)      # External run/job ID on that platform
    executed_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    status: WorkflowRunStatus = Field(default=WorkflowRunStatus.PENDING)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    created_by: str

    # Relationships
    workflow: Workflow = Relationship(back_populates="runs")
    attributes: List[WorkflowRunAttribute] | None = Relationship(back_populates="workflow_run")


# ---------------------------------------------------------------------------
# Request / Response models — Workflow
# ---------------------------------------------------------------------------

class WorkflowCreate(SQLModel):
    name: str
    version: str | None = None
    definition_uri: str
    attributes: List[Attribute] | None = None


class WorkflowPublic(SQLModel):
    id: uuid.UUID
    name: str
    version: str | None
    definition_uri: str
    created_at: datetime
    created_by: str
    attributes: List[Attribute] | None = None
    registrations: List["WorkflowRegistrationPublic"] | None = None


# ---------------------------------------------------------------------------
# Request / Response models — WorkflowRegistration
# ---------------------------------------------------------------------------

class WorkflowRegistrationCreate(SQLModel):
    engine: str
    external_id: str


class WorkflowRegistrationPublic(SQLModel):
    id: uuid.UUID
    workflow_id: uuid.UUID
    engine: str
    external_id: str
    created_at: datetime
    created_by: str


# ---------------------------------------------------------------------------
# Request / Response models — WorkflowRun
# ---------------------------------------------------------------------------

class WorkflowRunCreate(SQLModel):
    workflow_id: uuid.UUID
    engine: str
    engine_run_id: str | None = None
    executed_at: datetime | None = None
    status: WorkflowRunStatus = WorkflowRunStatus.PENDING
    attributes: List[Attribute] | None = None


class WorkflowRunUpdate(SQLModel):
    status: WorkflowRunStatus | None = None
    engine_run_id: str | None = None


class WorkflowRunPublic(SQLModel):
    id: uuid.UUID
    workflow_id: uuid.UUID
    workflow_name: str | None = None
    engine: str
    engine_run_id: str | None
    executed_at: datetime
    status: WorkflowRunStatus
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
