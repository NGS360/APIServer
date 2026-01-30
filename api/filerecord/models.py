"""
FileRecord Models - Reusable file metadata records.

These models provide a polymorphic file reference system that can associate
file metadata (URI, size, hashes, tags, samples) with various entity types.
"""

import uuid
from datetime import datetime
from enum import Enum
from typing import List
from sqlmodel import SQLModel, Field, Relationship, UniqueConstraint
from pydantic import ConfigDict


class FileRecordEntityType(str, Enum):
    """Entity types that can have file records associated."""
    QCRECORD = "QCRECORD"
    SAMPLE = "SAMPLE"


# ============================================================================
# Database Tables
# ============================================================================


class FileRecordHash(SQLModel, table=True):
    """
    Hash values for file records.
    Supports multiple hash algorithms (md5, sha256, etag, etc.) per file.
    """
    __tablename__ = "filerecordhash"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    file_record_id: uuid.UUID = Field(foreign_key="filerecord.id", nullable=False)
    algorithm: str = Field(max_length=50, nullable=False)
    value: str = Field(max_length=128, nullable=False)

    # Relationship back to parent
    file_record: "FileRecord" = Relationship(back_populates="hashes")

    __table_args__ = (
        UniqueConstraint("file_record_id", "algorithm", name="uq_filerecordhash_file_algorithm"),
    )


class FileRecordTag(SQLModel, table=True):
    """
    Key-value tags for file records.
    Allows arbitrary metadata to be attached to files.
    """
    __tablename__ = "filerecordtag"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    file_record_id: uuid.UUID = Field(foreign_key="filerecord.id", nullable=False)
    key: str = Field(max_length=255, nullable=False)
    value: str = Field(nullable=False)

    # Relationship back to parent
    file_record: "FileRecord" = Relationship(back_populates="tags")

    __table_args__ = (
        UniqueConstraint("file_record_id", "key", name="uq_filerecordtag_file_key"),
    )


class FileRecordSample(SQLModel, table=True):
    """
    Associates samples with a file record.

    Supports:
    - 0 rows: workflow-level file (e.g., expression matrix)
    - 1 row: single-sample file (e.g., BAM file)
    - N rows: multi-sample file with roles (e.g., tumor/normal VCF)
    """
    __tablename__ = "filerecordsample"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    file_record_id: uuid.UUID = Field(foreign_key="filerecord.id", nullable=False)
    sample_name: str = Field(max_length=255, nullable=False)
    role: str | None = Field(default=None, max_length=50)  # e.g., "tumor", "normal"

    # Relationship back to parent
    file_record: "FileRecord" = Relationship(back_populates="samples")

    __table_args__ = (
        UniqueConstraint("file_record_id", "sample_name", name="uq_filerecordsample_file_sample"),
    )


class FileRecord(SQLModel, table=True):
    """
    Metadata record for files stored in external locations (S3, etc.).

    Uses polymorphic association via entity_type and entity_id to link
    to parent entities (QCRecord, Sample, etc.) without hard FK constraints.
    """
    __tablename__ = "filerecord"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    entity_type: FileRecordEntityType = Field(nullable=False)
    entity_id: uuid.UUID = Field(nullable=False)
    uri: str = Field(max_length=1024, nullable=False)
    size: int | None = Field(default=None)  # File size in bytes
    created_on: datetime | None = Field(default=None)  # File creation timestamp

    # Relationships to child tables
    hashes: List["FileRecordHash"] = Relationship(
        back_populates="file_record",
        sa_relationship_kwargs={"cascade": "all, delete-orphan"}
    )
    tags: List["FileRecordTag"] = Relationship(
        back_populates="file_record",
        sa_relationship_kwargs={"cascade": "all, delete-orphan"}
    )
    samples: List["FileRecordSample"] = Relationship(
        back_populates="file_record",
        sa_relationship_kwargs={"cascade": "all, delete-orphan"}
    )

    model_config = ConfigDict(from_attributes=True)


# ============================================================================
# Request/Response Models (Pydantic)
# ============================================================================


class HashInput(SQLModel):
    """Hash input for file creation - key is algorithm, value is hash."""
    algorithm: str
    value: str


class TagInput(SQLModel):
    """Tag input for file creation."""
    key: str
    value: str


class SampleInput(SQLModel):
    """Sample association input for file creation."""
    sample_name: str
    role: str | None = None


class FileRecordCreate(SQLModel):
    """Request model for creating a file record."""
    uri: str
    size: int | None = None
    created_on: datetime | None = None
    hash: dict[str, str] | None = None  # {"md5": "abc...", "sha256": "def..."}
    tags: dict[str, str] | None = None  # {"type": "alignment", "format": "bam"}
    samples: List[SampleInput] | None = None  # Sample associations

    model_config = ConfigDict(extra="forbid")


class HashPublic(SQLModel):
    """Public representation of a file hash."""
    algorithm: str
    value: str


class TagPublic(SQLModel):
    """Public representation of a file tag."""
    key: str
    value: str


class SamplePublic(SQLModel):
    """Public representation of a sample association."""
    sample_name: str
    role: str | None


class FileRecordPublic(SQLModel):
    """Public representation of a file record."""
    id: uuid.UUID
    uri: str
    size: int | None
    created_on: datetime | None
    hashes: List[HashPublic]
    tags: List[TagPublic]
    samples: List[SamplePublic]
