"""
Models for the Project API
"""

from datetime import datetime, timezone
import uuid
from sqlmodel import SQLModel, Field, Relationship, UniqueConstraint
from typing import List
from pydantic import ConfigDict, field_validator

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
    download_restricted: bool = Field(default=False)

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
    model_config = ConfigDict(extra="forbid")


class ProjectUpdate(SQLModel):
    """
    Represents the data that can be updated for a project
    """
    name: str | None = None
    attributes: List[Attribute] | None = None
    # Guarded by `project:update` like the rest of this model. That is a
    # project-scoped permission, so restricting a project requires authority
    # over that project -- project_owner, or a global holder.
    download_restricted: bool | None = None


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
    download_restricted: bool = False
    attributes: List[Attribute] | None
    sequencing_runs: List[SequencingRunPublic] | None = None

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
