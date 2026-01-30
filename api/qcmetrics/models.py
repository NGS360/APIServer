"""
QCMetrics Models - Quality control metrics from pipeline executions.

These models store QC metrics and outputs from bioinformatics pipelines,
supporting workflow-level, single-sample, and multi-sample (paired) metrics.
"""

import uuid
from datetime import datetime, timezone
from typing import List
from sqlmodel import SQLModel, Field, Relationship, UniqueConstraint
from pydantic import ConfigDict

from api.filerecord.models import (
    FileRecordCreate,
    FileRecordPublic,
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

    The value_type column preserves the original Python type so values
    can be returned in their original format (int, float, or str).
    """
    __tablename__ = "qcmetricvalue"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    qc_metric_id: uuid.UUID = Field(foreign_key="qcmetric.id", nullable=False)
    key: str = Field(max_length=255, nullable=False)
    value: str = Field(nullable=False)
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
    sample_name: str = Field(max_length=255, nullable=False)
    role: str | None = Field(default=None, max_length=50)  # e.g., "tumor", "normal"

    # Relationship back to parent
    qc_metric: "QCMetric" = Relationship(back_populates="samples")

    __table_args__ = (
        UniqueConstraint("qc_metric_id", "sample_name", name="uq_qcmetricsample_metric_sample"),
    )


class QCMetric(SQLModel, table=True):
    """
    A named group of metrics within a QC record.

    Can be workflow-level (no samples), single-sample, or multi-sample (paired).
    Examples: alignment_stats, somatic_variants, expression_summary
    """
    __tablename__ = "qcmetric"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    qcrecord_id: uuid.UUID = Field(foreign_key="qcrecord.id", nullable=False)
    name: str = Field(max_length=255, nullable=False)

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

    __table_args__ = (
        UniqueConstraint("qcrecord_id", "name", name="uq_qcmetric_record_name"),
    )


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


class QCRecordCreate(SQLModel):
    """
    Request model for creating a QC record.

    Uses the explicit metrics format with sample associations supporting
    workflow-level, single-sample, and paired-sample (tumor/normal) metrics.
    """
    project_id: str
    metadata: dict[str, str] | None = None  # {"pipeline": "RNA-Seq", "version": "2.0"}
    metrics: List[MetricInput] | None = None  # Metrics with explicit sample associations
    output_files: List[FileRecordCreate] | None = None

    model_config = ConfigDict(extra="forbid")


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


class QCRecordPublic(SQLModel):
    """Public representation of a QC record."""
    id: uuid.UUID
    created_on: datetime
    created_by: str
    project_id: str
    metadata: List[MetadataKeyValue]
    metrics: List[MetricPublic]
    output_files: List[FileRecordPublic]


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
