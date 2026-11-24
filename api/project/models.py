"""
Models for the Project API
"""

from datetime import datetime, timezone
import gzip
import hashlib
import uuid
from sqlalchemy import JSON, Column, LargeBinary
from sqlalchemy import ForeignKeyConstraint
from sqlalchemy.dialects import mysql
from sqlmodel import SQLModel, Field, Relationship, UniqueConstraint
from typing import List
from pydantic import ConfigDict, field_validator

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
    # Populated on the detail, update and patch routes, and left None by the
    # list routes, the same way sequencing_runs is. Resolving it costs a membership lookup per
    # project, which on a page of projects is an N+1 for something no list view
    # needs -- there are no per-row actions to gate.
    #
    # None is not the same as []. None means the field was not populated -- the
    # list and create routes return this model without resolving it; [] means
    # this caller genuinely holds nothing here.
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


class WorkflowAttribute(SQLModel, table=True):
    """ Attribute of a workflow """
    __table_args__ = (
        UniqueConstraint("workflow_id", "key", name="uq_workflow_attribute_key"),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    workflow_id: uuid.UUID = Field(foreign_key="projectworkflow.id")
    key: str
    value: str

    # Relationships
    workflow: "ProjectWorkflow" = Relationship(back_populates="attributes")


class WorkflowVersionAttribute(SQLModel, table=True):
    """ Attribute of a specific version of a workflow """
    __table_args__ = (
        UniqueConstraint(
            "workflowversion_id", "key", name="uq_workflow_version_attribute_key",
        ),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    workflowversion_id: uuid.UUID = Field(foreign_key="workflowversion.id")
    key: str
    value: str

    # Relationships
    workflowversion: "WorkflowVersion" = Relationship(back_populates="attributes")


class WorkflowVersionAlias(SQLModel, table=True):
    """ Named pointer to a specific version of a workflow (e.g. production, development). """
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
    workflow_id: uuid.UUID = Field(foreign_key="projectworkflow.id")
    workflow_version_id: uuid.UUID
    alias: str

    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    created_by: str = Field(foreign_key="users.username")

    updated_at: datetime | None = None
    updated_by: str | None = Field(foreign_key="users.username", default=None)

    # Relationships
    workflow: "ProjectWorkflow" = Relationship(back_populates="aliases")
    # Read-only: workflow_id/workflow_version_id are written by the columns, and the
    # composite FK already overlaps the workflow relationship.
    workflow_version: "WorkflowVersion" = Relationship(
        sa_relationship_kwargs={"viewonly": True},
    )


class WorkflowVersion(SQLModel, table=True):
    """
    Versioned definition of a workflow.

    `version` is assigned by the service layer (max + 1 per workflow); the unique
    constraint on (workflow_id, version) rejects a concurrent duplicate.

    `body` is the authoritative copy of the workflow text, stored compressed.
    `compression` names the codec used; the default and currently only supported
    value is "gzip". Decode with gzip.decompress(body).
    `content_hash` is the SHA-256 hex digest of the *uncompressed* text, so the
    integrity of `body` can be verified after decompression. It is computed
    from `body` on construction and must not be supplied by the caller.
    `definition_uri` is a source reference only and may be overwritten.
    """

    def __init__(self, **data):
        # SQLModel skips validators on table models, so compute the hash here.
        # Rows loaded from the database do not pass through __init__.
        body = data.get("body")
        if body is not None:
            if data.get("compression", "gzip") != "gzip":
                raise ValueError(
                    f"Unsupported compression: {data.get('compression')!r}")
            computed = hashlib.sha256(gzip.decompress(body)).hexdigest()
            supplied = data.get("content_hash")
            if supplied is not None and supplied != computed:
                raise ValueError("content_hash does not match body")
            data["content_hash"] = computed
        super().__init__(**data)
    __table_args__ = (
        UniqueConstraint("workflow_id", "version", name="uq_workflow_version"),
        # Target for the composite FK from WorkflowVersionAlias.
        UniqueConstraint("workflow_id", "id", name="uq_workflow_version_workflow_id"),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    workflow_id: uuid.UUID = Field(foreign_key="projectworkflow.id")
    version: int

    # Source reference only; may be overwritten, so `body` is the authoritative copy.
    definition_uri: str
    # Compressed binary of the workflow text. LONGBLOB: MySQL BLOB caps at 64 KB.
    body: bytes = Field(
        sa_column=Column(
            LargeBinary().with_variant(mysql.LONGBLOB(), "mysql"),
            nullable=False,
        ),
    )
    # Codec used for `body`. Default and only supported value: "gzip".
    compression: str = Field(default="gzip", max_length=16)
    # SHA-256 hex digest of the uncompressed workflow text.
    content_hash: str = Field(max_length=64)

    inputs: list[dict] | None = Field(default=None, sa_column=Column(JSON))
    outputs: list[dict] | None = Field(default=None, sa_column=Column(JSON))

    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    created_by: str = Field(foreign_key="users.username")

    # Relationships
    workflow: "ProjectWorkflow" = Relationship(back_populates="versions")
    attributes: List["WorkflowVersionAttribute"] | None = Relationship(
        back_populates="workflowversion",
    )
    # deployments: List["WorkflowDeployment"] | None = Relationship(
    #    back_populates="workflowversion",
    # )


class ProjectWorkflow(SQLModel, table=True):
    """
    A workflow within a project.
    """
    __table_args__ = (
        UniqueConstraint("project_id", "name", name="uq_project_workflow_name"),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    project_id: str = Field(foreign_key="project.project_id")
    name: str

    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    created_by: str = Field(foreign_key="users.username")

    # Relationships
    attributes: List["WorkflowAttribute"] | None = Relationship(back_populates="workflow")
    versions: List["WorkflowVersion"] | None = Relationship(back_populates="workflow")
    aliases: List["WorkflowVersionAlias"] | None = Relationship(back_populates="workflow")
