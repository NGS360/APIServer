"""
Pipeline Models

Pipeline — A named collection of workflows
PipelineAttribute — Key-value metadata for pipelines
PipelineWorkflow — Junction table linking pipelines to workflows (simple membership)
"""
import uuid
from datetime import datetime, timezone
from typing import List

from sqlmodel import Field, Relationship, SQLModel, UniqueConstraint

from api.workflow.models import Attribute


# ---------------------------------------------------------------------------
# Database tables
# ---------------------------------------------------------------------------

class PipelineAttribute(SQLModel, table=True):
    __tablename__ = "pipelineattribute"
    __table_args__ = (
        UniqueConstraint("pipeline_id", "key", name="uq_pipeline_attr_key"),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    pipeline_id: uuid.UUID = Field(foreign_key="pipeline.id")
    key: str
    value: str

    # Relationships
    pipeline: "Pipeline" = Relationship(back_populates="attributes")


class Pipeline(SQLModel, table=True):
    """A named collection of workflows."""
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    name: str
    version: str | None = Field(default=None)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    created_by: str

    # Relationships
    attributes: List[PipelineAttribute] | None = Relationship(back_populates="pipeline")
    pipeline_workflows: List["PipelineWorkflow"] | None = Relationship(back_populates="pipeline")


class PipelineWorkflow(SQLModel, table=True):
    """Junction table: simple membership of a workflow in a pipeline (no ordering).
    See plans/phase1-decisions-pipeline-workflow-relationships.md for rationale.
    """
    __tablename__ = "pipelineworkflow"
    __table_args__ = (
        UniqueConstraint("pipeline_id", "workflow_id", name="uq_pipeline_workflow"),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    pipeline_id: uuid.UUID = Field(foreign_key="pipeline.id")
    workflow_id: uuid.UUID = Field(foreign_key="workflow.id")
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    created_by: str

    # Relationships
    pipeline: Pipeline = Relationship(back_populates="pipeline_workflows")


# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------

class WorkflowSummary(SQLModel):
    """Lightweight workflow reference for inclusion in pipeline responses."""
    id: uuid.UUID
    name: str
    version: str | None = None


class PipelineCreate(SQLModel):
    name: str
    version: str | None = None
    attributes: List[Attribute] | None = None
    workflow_ids: List[uuid.UUID] | None = None


class PipelinePublic(SQLModel):
    id: uuid.UUID
    name: str
    version: str | None
    created_at: datetime
    created_by: str
    attributes: List[Attribute] | None = None
    workflows: List[WorkflowSummary] | None = None


class PipelinesPublic(SQLModel):
    """Paginated list of pipelines."""
    data: List[PipelinePublic]
    total_items: int
    total_pages: int
    current_page: int
    per_page: int
    has_next: bool
    has_prev: bool
