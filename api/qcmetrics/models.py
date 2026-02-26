"""
QCMetrics Models - Quality control metrics from pipeline executions.

These models store QC metrics and outputs from bioinformatics pipelines,
supporting workflow-level, single-sample, and multi-sample (paired) metrics.
"""

import uuid
from datetime import datetime, timezone
from typing import List
from sqlmodel import SQLModel, Field, Relationship, UniqueConstraint
from pydantic import BaseModel, ConfigDict, model_validator

from api.files.models import (
    FileCreate,
    FileSummary,
)


# ============================================================================
# Database Tables
# ============================================================================


class QCRecordMetadata(SQLModel, table=True):
    """
    Key-value store for pipeline-level metadata.
    Examples: pipeline name, version, configuration parameters.
    """
    __tablename__ = "qcrecordmetadata"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    qcrecord_id: uuid.UUID = Field(foreign_key="qcrecord.id", nullable=False)
    key: str = Field(max_length=255, nullable=False)
    value: str = Field(nullable=False)

    # Relationship back to parent
    qcrecord: "QCRecord" = Relationship(back_populates="pipeline_metadata")

    __table_args__ = (
        UniqueConstraint("qcrecord_id", "key", name="uq_qcrecordmetadata_record_key"),
    )


class QCMetricValue(SQLModel, table=True):
    """
    Key-value store for individual metric values within a metric group.
    Examples: reads=50000000, alignment_rate=95.5, tmb=8.5

    Stores values in two formats:
    - value_string: Always populated, used for string matching and display
    - value_numeric: Populated only for int/float types, enables numeric queries
      (greater than, less than, range, aggregations)
    - value_type: Preserves original Python type ("str", "int", "float")
    """
    __tablename__ = "qcmetricvalue"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    qc_metric_id: uuid.UUID = Field(foreign_key="qcmetric.id", nullable=False)
    key: str = Field(max_length=255, nullable=False)
    value_string: str = Field(nullable=False)
    value_numeric: float | None = Field(default=None, nullable=True)  # For numeric queries
    value_type: str = Field(max_length=10, default="str")  # "str", "int", "float"

    # Relationship back to parent
    qc_metric: "QCMetric" = Relationship(back_populates="values")

    __table_args__ = (
        UniqueConstraint("qc_metric_id", "key", name="uq_qcmetricvalue_metric_key"),
    )


class QCMetricSample(SQLModel, table=True):
    """
    Associates samples with a metric group.

    Supports:
    - 0 rows: workflow-level metric (e.g., pipeline runtime)
    - 1 row: single-sample metric (e.g., alignment stats for Sample1)
    - N rows: multi-sample metric with roles (e.g., tumor/normal somatic variants)
    """
    __tablename__ = "qcmetricsample"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    qc_metric_id: uuid.UUID = Field(foreign_key="qcmetric.id", nullable=False)
    sample_id: uuid.UUID = Field(foreign_key="sample.id", nullable=False, index=True)
    role: str | None = Field(default=None, max_length=50)  # e.g., "tumor", "normal"

    # Relationship back to parent
    qc_metric: "QCMetric" = Relationship(back_populates="samples")

    __table_args__ = (
        UniqueConstraint("qc_metric_id", "sample_id", name="uq_qcmetricsample_metric_sample"),
    )


class QCMetric(SQLModel, table=True):
    """
    A named group of metrics within a QC record.

    Can be workflow-level (no samples), single-sample, or multi-sample (paired).
    Examples: sample_qc, somatic_variants, pipeline_summary

    Multiple QCMetric rows with the same name are allowed within a QCRecord,
    differentiated by their sample associations in QCMetricSample.
    For example, each sample gets its own QCMetric(name="sample_qc") row.
    """
    __tablename__ = "qcmetric"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    qcrecord_id: uuid.UUID = Field(foreign_key="qcrecord.id", nullable=False, index=True)
    name: str = Field(max_length=255, nullable=False, index=True)

    # Relationships to child tables
    values: List["QCMetricValue"] = Relationship(
        back_populates="qc_metric",
        sa_relationship_kwargs={"cascade": "all, delete-orphan"}
    )
    samples: List["QCMetricSample"] = Relationship(
        back_populates="qc_metric",
        sa_relationship_kwargs={"cascade": "all, delete-orphan"}
    )

    # Relationship back to parent
    qcrecord: "QCRecord" = Relationship(back_populates="metrics")


class QCRecord(SQLModel, table=True):
    """
    Main QC record entity - one per pipeline execution per project.

    Multiple records per project are allowed for versioning (history).
    The created_on timestamp differentiates versions.
    """
    __tablename__ = "qcrecord"
    __searchable__ = ["project_id"]

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    created_on: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        nullable=False
    )
    created_by: str = Field(max_length=100, nullable=False)
    project_id: str = Field(max_length=50, nullable=False, index=True)

    # Relationships to child tables
    pipeline_metadata: List["QCRecordMetadata"] = Relationship(
        back_populates="qcrecord",
        sa_relationship_kwargs={"cascade": "all, delete-orphan"}
    )
    metrics: List["QCMetric"] = Relationship(
        back_populates="qcrecord",
        sa_relationship_kwargs={"cascade": "all, delete-orphan"}
    )

    model_config = ConfigDict(from_attributes=True)


# ============================================================================
# Request/Response Models (Pydantic)
# ============================================================================


class MetadataKeyValue(SQLModel):
    """Key-value pair for metadata."""
    key: str
    value: str


class MetricValueInput(SQLModel):
    """Key-value pair for metric values."""
    key: str
    value: str


class MetricSampleInput(SQLModel):
    """Sample association input for metrics."""
    sample_name: str
    role: str | None = None


class MetricInput(SQLModel):
    """Input model for a metric group."""
    name: str
    samples: List[MetricSampleInput] | None = None
    values: dict[str, str | int | float]  # {"reads": 50000000, "alignment_rate": 95.5}


class QCRecordCreate(BaseModel):
    """
    Request model for creating a QC record.

    Uses the explicit metrics format with sample associations supporting
    workflow-level, single-sample, and paired-sample (tumor/normal) metrics.
    """
    project_id: str
    metadata: dict[str, str] | None = None  # {"pipeline": "RNA-Seq", "version": "2.0"}
    metrics: List[MetricInput] | None = None  # Metrics with explicit sample associations
    output_files: List[FileCreate] | None = None

    model_config = ConfigDict(extra="forbid")

    @model_validator(mode="before")
    @classmethod
    def propagate_project_id_to_files(cls, data):
        """Propagate project_id to nested FileCreate objects before validation."""
        if isinstance(data, dict):
            project_id = data.get("project_id")
            if project_id and data.get("output_files"):
                for f in data["output_files"]:
                    if isinstance(f, dict) and not f.get("project_id"):
                        f["project_id"] = project_id
        return data


class MetricValuePublic(SQLModel):
    """Public representation of a metric value with original type preserved."""
    key: str
    value: str | int | float


class MetricSamplePublic(SQLModel):
    """Public representation of a sample association."""
    sample_name: str
    role: str | None


class MetricPublic(SQLModel):
    """Public representation of a metric group."""
    name: str
    samples: List[MetricSamplePublic]
    values: List[MetricValuePublic]


class QCRecordPublic(BaseModel):
    """Public representation of a QC record."""
    id: uuid.UUID
    created_on: datetime
    created_by: str
    project_id: str
    metadata: List[MetadataKeyValue]
    metrics: List[MetricPublic]
    output_files: List[FileSummary]


class QCRecordCreated(SQLModel):
    """
    Minimal response model for QC record creation.

    Returns only essential fields to reduce response size.
    Use GET /api/v1/qcmetrics/{id} to retrieve full details.
    """
    id: uuid.UUID
    created_on: datetime
    created_by: str
    project_id: str
    is_duplicate: bool = False


class QCRecordsPublic(SQLModel):
    """Paginated list of QC records."""
    data: List[QCRecordPublic]
    total: int
    page: int
    per_page: int


class QCRecordSearchRequest(SQLModel):
    """Request model for searching QC records."""
    filter_on: dict | None = None  # Flexible filtering
    page: int = 1
    per_page: int = 100
    latest: bool = True  # Return only newest version per project

    model_config = ConfigDict(extra="forbid")
