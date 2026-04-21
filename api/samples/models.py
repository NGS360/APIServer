"""
Models for the Sample API
"""

import uuid
from datetime import datetime
from typing import List, TYPE_CHECKING
from sqlmodel import SQLModel, Field, Relationship, UniqueConstraint
from pydantic import ConfigDict, field_validator

if TYPE_CHECKING:
    from api.project.models import Project
    from api.files.models import FileSample


class Attribute(SQLModel):
    key: str | None
    value: str | None


class SampleAttribute(SQLModel, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    sample_id: uuid.UUID = Field(foreign_key="sample.id")
    key: str
    value: str
    __table_args__ = (UniqueConstraint("sample_id", "key"),)

    sample: "Sample" = Relationship(back_populates="attributes")


class Sample(SQLModel, table=True):
    __searchable__ = ["sample_id"]

    id: uuid.UUID | None = Field(default_factory=uuid.uuid4, primary_key=True)
    sample_id: str
    project_id: str = Field(foreign_key="project.project_id")
    created_at: datetime | None = Field(default=None)
    updated_at: datetime | None = Field(default=None)
    attributes: List[SampleAttribute] | None = Relationship(back_populates="sample")
    project: "Project" = Relationship(back_populates="samples")
    file_samples: List["FileSample"] | None = Relationship(back_populates="sample")

    model_config = ConfigDict(from_attributes=True)

    __table_args__ = (UniqueConstraint("sample_id", "project_id"),)


class SampleFileInput(SQLModel):
    """File to create and associate with a sample during sample creation."""
    uri: str
    tags: dict[str, str] | None = None
    hashes: dict[str, str] | None = None     # {"md5": "abc...", "sha256": "def..."}
    role: str | None = None                   # FileSample.role (tumor/normal/etc.)
    source: str | None = None
    original_filename: str | None = None
    size: int | None = None
    storage_backend: str | None = None


class SampleCreate(SQLModel):
    sample_id: str
    attributes: List[Attribute] | None = None
    run_barcode: str | None = None
    files: List[SampleFileInput] | None = None
    model_config = ConfigDict(extra="forbid")


class SamplePublic(SQLModel):
    sample_id: str
    project_id: str
    attributes: List[Attribute] | None
    run_barcode: str | None = None


class SamplesPublic(SQLModel):
    data: List[SamplePublic]
    data_cols: list[str] | None = None
    total_items: int
    total_pages: int
    current_page: int
    per_page: int
    has_next: bool
    has_prev: bool


# ---------------------------------------------------------------------------
# Sample-with-files response models (for ?include=files)
# ---------------------------------------------------------------------------


class SampleFilePublic(SQLModel):
    """Compact file representation for sample responses."""
    uri: str
    tags: dict[str, str] | None = None  # Flattened from List[FileTag]


class SampleWithFilesPublic(SamplePublic):
    """SamplePublic extended with associated files."""
    files: List[SampleFilePublic] | None = None


class SamplesWithFilesPublic(SQLModel):
    """Paginated list of samples with file data included."""
    data: List[SampleWithFilesPublic]
    data_cols: list[str] | None = None
    total_items: int
    total_pages: int
    current_page: int
    per_page: int
    has_next: bool
    has_prev: bool


# ---------------------------------------------------------------------------
# Bulk sample creation models
# ---------------------------------------------------------------------------


class BulkSampleCreateRequest(SQLModel):
    """Request body for POST /projects/{project_id}/samples/bulk."""
    samples: List[SampleCreate]

    @field_validator("samples")
    @classmethod
    def samples_must_not_be_empty(cls, v: List[SampleCreate]) -> List[SampleCreate]:
        if not v:
            raise ValueError("samples list must not be empty")
        return v


class BulkSampleItemResponse(SQLModel):
    """Per-item detail in the bulk creation response."""
    sample_id: str
    sample_uuid: uuid.UUID
    project_id: str
    created: bool
    run_barcode: str | None = None
    files_created: int = 0
    files_skipped: int = 0


class BulkSampleCreateResponse(SQLModel):
    """Aggregate response for the bulk sample creation endpoint."""
    project_id: str
    samples_created: int
    samples_existing: int
    associations_created: int
    associations_existing: int
    files_created: int = 0
    files_skipped: int = 0
    items: List[BulkSampleItemResponse]
