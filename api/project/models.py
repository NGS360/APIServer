"""
Models for the Project API
"""

from datetime import datetime, timezone
import uuid
from sqlalchemy import ForeignKeyConstraint
from sqlmodel import SQLModel, Field, Relationship, UniqueConstraint
from typing import List
from pydantic import ConfigDict, field_validator, model_validator

from api.rbac.permissions import Permission
from api.runs.models import SequencingRunPublic
from api.samples.models import Sample
from api.qcmetrics.models import QCRecord

# Shared with samples and workflows: one definition keeps the generated OpenAPI
# schema name stable. Re-exported here so `from api.project.models import
# Attribute` keeps working.
from core.models import Attribute


class ProjectAttribute(SQLModel, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    project_id: uuid.UUID = Field(foreign_key="project.id", primary_key=True)
    key: str
    value: str

    projects: List["Project"] = Relationship(back_populates="attributes")
    __table_args__ = (UniqueConstraint("project_id", "key"),)


class Project(SQLModel, table=True):
    __searchable__ = ["project_id", "name"]

    id: uuid.UUID | None = Field(default_factory=uuid.uuid4, primary_key=True)
    project_id: str = Field(unique=True)
    name: str | None = Field(max_length=2048)

    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    created_by: str

    # Downloads are open to any authenticated user unless a project opts out by
    # setting this. Only then is `file:download` consulted, against the project
    # plane -- so restriction is expressed by project membership.
    #
    # Default-false means the platform's resting posture is permissive and a
    # project is only as protected as someone actively made it. That is the
    # deliberate trade recorded in docs/RBAC.md: the previous default-deny model
    # made every project safe and made one legitimate 33M-request genomics
    # workload require 66 project grants.
    # Renamed from download_restricted on 2026-10-08. The flag was introduced for
    # downloads alone; it now marks a project locked down for *every* action, so
    # the narrower name was actively misleading. Safe to rename rather than add a
    # second flag because it is set on 0 of 11,156 projects -- there is no data
    # to migrate and no caller relying on the old behaviour.
    restricted: bool = Field(default=False)

    last_modified: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column_kwargs={"onupdate": lambda: datetime.now(timezone.utc)}
    )

    attributes: List[ProjectAttribute] | None = Relationship(back_populates="projects")
    samples: List["Sample"] = Relationship(back_populates="project")
    qcrecords: List["QCRecord"] = Relationship(back_populates="project")

    model_config = ConfigDict(from_attributes=True)


class ProjectCreate(SQLModel):
    name: str
    attributes: List[Attribute] | None = None
    restricted: bool = False
    model_config = ConfigDict(extra="forbid")


class ProjectUpdate(SQLModel):
    """
    Represents the data that can be updated for a project
    """
    name: str | None = None
    attributes: List[Attribute] | None = None
    # The one field on this model that is not covered by `project:update`.
    # Changing it requires `project:restrict`, which `member` does not hold --
    # see require_project_restrict in api/project/routes.py for why, and note
    # the check fires only when the value actually changes, so a client echoing
    # the current value back is unaffected.
    restricted: bool | None = None


class ProjectPublic(SQLModel):
    project_id: str
    name: str | None
    created_by: str
    created_at: datetime | None
    last_modified: datetime | None
    data_folder_uri: str | None
    results_folder_uri: str | None
    # Surfaced deliberately: with an opt-in control, the dangerous state is a
    # project nobody remembered to restrict, and that is only discoverable if
    # the flag is visible rather than implied by its absence.
    restricted: bool = False
    attributes: List[Attribute] | None
    sequencing_runs: List[SequencingRunPublic] | None = None

    # What the *calling* user may do in this project, so a UI can decide which
    # controls to render rather than rendering them all and absorbing 403s.
    #
    # Per-caller, unlike every other field here: two users get different values
    # for the same project_id. This response must therefore never go into a
    # shared or CDN cache.
    #
    # Populated on the detail route only, and left None by the list routes, the
    # same way sequencing_runs is. Resolving it costs a membership lookup per
    # project, which on a page of projects is an N+1 for something no list view
    # needs -- there are no per-row actions to gate.
    #
    # None is not the same as []. None means the field was not populated -- the
    # list, create, update and patch routes all return this model without
    # resolving it; [] means this caller genuinely holds nothing here.
    #
    # None once also covered an anonymous caller. It no longer can: the detail
    # route requires a caller and then project:read, so a request that reaches
    # the handler always has somebody to report on.
    permissions: List[Permission] | None = None

    @field_validator("created_at", "last_modified", mode="before")
    @classmethod
    def _nullify_invalid_datetime(cls, value):
        """
        Map unparseable dates to None.

        MySQL can store invalid "zero dates" (e.g. '1000-00-01 00:00:00',
        month value 0) that the driver hands back as a raw string. These
        cannot be parsed into a datetime, so surface them as None instead
        of raising a ValidationError that would fail the whole request.
        """
        if isinstance(value, str):
            try:
                datetime.fromisoformat(value)
            except ValueError:
                return None
        return value


class ProjectsPublic(SQLModel):
    data: List[ProjectPublic]
    total_items: int
    total_pages: int
    current_page: int
    per_page: int
    has_next: bool
    has_prev: bool


class ProjectWorkflowVersion(SQLModel, table=True):
    """
    The workflow version a project uses, per workflow and engine.

    Recorded on the project's first run, from an alias or an explicit version,
    then reused: later runs get this version whatever they request, until it is
    changed with PUT or deleted.
    """
    __tablename__ = "projectworkflowversion"
    __table_args__ = (
        # One version per project, workflow and engine: the guarantee that a
        # project cannot end up with two versions of the same workflow.
        UniqueConstraint(
            "project_id", "workflow_id", "engine", name="uq_project_workflow_engine"
        ),
        ForeignKeyConstraint(
            ["workflow_id", "version"],
            ["workflowversion.workflow_id", "workflowversion.version"],
            name="fk_projectworkflowversion_workflowversion",
        ),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    project_id: str = Field(foreign_key="project.project_id")
    workflow_id: uuid.UUID = Field(foreign_key="workflow.id")
    version: int
    engine: str = Field(foreign_key="platform.name")
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    created_by: str
    # Set only when someone chose the version explicitly, via PUT.
    updated_at: datetime | None = None
    updated_by: str | None = None


class ProjectWorkflowVersionResolve(SQLModel):
    """
    An existing record always wins. Without one, `alias`
    or `version` says what to record; with neither, nothing is written.
    """
    engine: str
    alias: str | None = None
    version: int | None = None

    @model_validator(mode="after")
    def _not_both(self):
        if self.alias is not None and self.version is not None:
            raise ValueError("Give 'alias' or 'version', not both.")
        return self


class ProjectWorkflowVersionSet(SQLModel):
    engine: str
    version: int


class ProjectWorkflowVersionPublic(SQLModel):
    project_id: str
    workflow_id: uuid.UUID
    version: int
    engine: str
    # The deployment's id on `engine`, for logging; WES does its own selection.
    external_id: str | None = None
    # True only on the resolve call that created the record.
    created: bool = False
    # Set when resolve returned an existing record instead of what was requested.
    message: str | None = None
    created_at: datetime
    created_by: str
    updated_at: datetime | None = None
    updated_by: str | None = None
