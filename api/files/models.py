"""
Unified File Models - Supporting both file uploads and external file references.

This module provides a unified file metadata system that supports:
- Both file uploads and external file references
- Many-to-many relationships with any entity type via FileEntity
- Flexible sample associations with roles via FileSample
- Multi-algorithm hash storage via FileHash
- Flexible key-value tags via FileTag
"""

from datetime import datetime, timezone
import hashlib
import uuid
from typing import List

from pydantic import ConfigDict
from sqlmodel import Field, Relationship, SQLModel, UniqueConstraint


# ============================================================================
# Entity Type Constants
# ============================================================================


class FileEntityType:
    """
    Entity types that can have files associated.
    
    Note: Using class constants instead of Enum for flexibility.
    Entity types stored as VARCHAR in database.
    """
    PROJECT = "PROJECT"
    RUN = "RUN"
    SAMPLE = "SAMPLE"
    QCRECORD = "QCRECORD"


# ============================================================================
# Database Tables
# ============================================================================


class FileHash(SQLModel, table=True):
    """
    Hash values for files (supports multiple algorithms).
    
    Supports: md5, sha256, etag, etc.
    """
    __tablename__ = "filehash"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    file_id: uuid.UUID = Field(foreign_key="file.id", nullable=False)
    algorithm: str = Field(max_length=50, nullable=False)
    value: str = Field(max_length=128, nullable=False)

    # Relationship back to parent
    file: "File" = Relationship(back_populates="hashes")

    __table_args__ = (
        UniqueConstraint("file_id", "algorithm", name="uq_filehash_file_algorithm"),
    )


class FileTag(SQLModel, table=True):
    """
    Flexible key-value metadata for files.
    
    Standard tags:
    - archived: true/false
    - public: true/false
    - description: file description
    - type: alignment, variant, expression, qc_report, etc.
    - format: bam, vcf, fastq, csv, etc.
    """
    __tablename__ = "filetag"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    file_id: uuid.UUID = Field(foreign_key="file.id", nullable=False)
    key: str = Field(max_length=255, nullable=False)
    value: str = Field(nullable=False)

    # Relationship back to parent
    file: "File" = Relationship(back_populates="tags")

    __table_args__ = (
        UniqueConstraint("file_id", "key", name="uq_filetag_file_key"),
    )


class FileSample(SQLModel, table=True):
    """
    Associates samples with a file (supports roles for paired analysis).
    
    Supports:
    - 0 rows: workflow-level file (e.g., expression matrix)
    - 1 row: single-sample file (e.g., BAM file)
    - N rows: multi-sample file with roles (e.g., tumor/normal VCF)
    """
    __tablename__ = "filesample"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    file_id: uuid.UUID = Field(foreign_key="file.id", nullable=False)
    sample_name: str = Field(max_length=255, nullable=False)
    role: str | None = Field(default=None, max_length=50)  # e.g., "tumor", "normal"

    # Relationship back to parent
    file: "File" = Relationship(back_populates="samples")

    __table_args__ = (
        UniqueConstraint("file_id", "sample_name", name="uq_filesample_file_sample"),
    )


class FileEntity(SQLModel, table=True):
    """
    Many-to-many junction table linking files to entities.
    
    Examples:
    - Sample sheet: entity_type=RUN, entity_id=barcode, role=samplesheet
    - Pipeline output: entity_type=QCRECORD, entity_id=uuid, role=output
    - Project manifest (standalone): entity_type=PROJECT, entity_id=P-12345, role=manifest
    
    Important: Files attached to Samples or QCRecords should NOT also be linked
    to their parent Project via FileEntity. The project relationship can be
    traversed through the Sample→Project or QCRecord→Project relationships.
    Project-level FileEntity associations are only for standalone files
    (manifests, etc.) that have no other entity association.
    """
    __tablename__ = "fileentity"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    file_id: uuid.UUID = Field(foreign_key="file.id", nullable=False)
    entity_type: str = Field(max_length=50, nullable=False)  # PROJECT, RUN, SAMPLE, QCRECORD
    entity_id: str = Field(max_length=100, nullable=False)  # Entity identifier
    role: str | None = Field(default=None, max_length=50)  # e.g., samplesheet, manifest, output

    # Relationship back to parent
    file: "File" = Relationship(back_populates="entities")

    __table_args__ = (
        UniqueConstraint("file_id", "entity_type", "entity_id", name="uq_fileentity_file_entity"),
    )


class File(SQLModel, table=True):
    """
    Core file entity supporting both uploads and external references.
    
    This unified model replaces both the original File model (upload-focused)
    and FileRecord model (reference-focused).
    
    The `uri` field is the file location. Filename can be derived as
    `uri.split('/')[-1]`. Same URI can exist multiple times with different
    `created_on` timestamps, enabling versioning.
    
    Version queries:
    - Latest version: WHERE uri = ? ORDER BY created_on DESC LIMIT 1
    - All versions: WHERE uri = ? ORDER BY created_on
    """
    __tablename__ = "file"
    __searchable__ = ["uri"]

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    uri: str = Field(max_length=1024)  # File location (not unique alone)
    original_filename: str | None = Field(default=None, max_length=255)  # For uploads only
    size: int | None = Field(default=None)  # File size in bytes (BIGINT in DB)
    created_on: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    created_by: str | None = Field(default=None, max_length=100)  # User identifier
    source: str | None = Field(default=None, max_length=1024)  # Origin of file record
    storage_backend: str | None = Field(default=None, max_length=20)  # LOCAL, S3, AZURE, GCS

    # Composite unique constraint: uri + created_on enables versioning
    __table_args__ = (
        UniqueConstraint("uri", "created_on", name="uq_file_uri_created_on"),
    )

    # Relationships to child tables
    entities: List["FileEntity"] = Relationship(
        back_populates="file",
        sa_relationship_kwargs={"cascade": "all, delete-orphan"}
    )
    hashes: List["FileHash"] = Relationship(
        back_populates="file",
        sa_relationship_kwargs={"cascade": "all, delete-orphan"}
    )
    tags: List["FileTag"] = Relationship(
        back_populates="file",
        sa_relationship_kwargs={"cascade": "all, delete-orphan"}
    )
    samples: List["FileSample"] = Relationship(
        back_populates="file",
        sa_relationship_kwargs={"cascade": "all, delete-orphan"}
    )

    model_config = ConfigDict(from_attributes=True)

    @property
    def filename(self) -> str:
        """Derive filename from URI."""
        return self.uri.split("/")[-1] if self.uri else ""

    @staticmethod
    def generate_uri(
        base_path: str,
        entity_type: str,
        entity_id: str,
        filename: str,
        relative_path: str | None = None,
    ) -> str:
        """
        Generate a structured URI for file storage.

        Args:
            base_path: Storage root (e.g., s3://bucket)
            entity_type: Type of entity (project, run, sample, qcrecord)
            entity_id: ID of the entity
            filename: Name of the file
            relative_path: Optional subdirectory path (e.g., "raw_data/sample1")

        Returns:
            Full URI string

        Examples:
            generate_uri("s3://bucket", "project", "P-123", "file.txt")
            => "s3://bucket/project/P-123/file.txt"

            generate_uri("s3://bucket", "project", "P-123", "file.txt", "raw_data")
            => "s3://bucket/project/P-123/raw_data/file.txt"
        """
        # Build path components
        path_parts = [base_path.rstrip("/"), entity_type.lower(), entity_id]

        # Add subdirectory if provided
        if relative_path:
            normalized = relative_path.strip("/")
            if normalized:
                path_parts.append(normalized)

        # Add filename
        path_parts.append(filename)

        return "/".join(path_parts)

    @staticmethod
    def validate_relative_path(relative_path: str | None) -> str | None:
        """
        Validate and sanitize relative path to prevent security issues.

        Args:
            relative_path: Path to validate

        Returns:
            Sanitized path or None

        Raises:
            ValueError: If path contains invalid characters or patterns
        """
        if not relative_path:
            return None

        if relative_path.startswith("/"):
            raise ValueError("Absolute paths not allowed")

        if "//" in relative_path:
            raise ValueError("Double slashes not allowed")

        path = relative_path.strip("/")

        if not path:
            return None

        if ".." in path:
            raise ValueError("Path traversal not allowed (..)")

        import re
        if not re.match(r"^[a-zA-Z0-9_\-/]+$", path):
            raise ValueError(
                "Invalid characters in path. "
                "Only alphanumeric, dash, underscore, and forward slash allowed"
            )

        return path

    @staticmethod
    def calculate_checksum(file_content: bytes, algorithm: str = "sha256") -> str:
        """Calculate checksum of file content."""
        if algorithm == "sha256":
            return hashlib.sha256(file_content).hexdigest()
        elif algorithm == "md5":
            return hashlib.md5(file_content).hexdigest()
        else:
            raise ValueError(f"Unsupported hash algorithm: {algorithm}")

    @staticmethod
    def get_mime_type(filename: str) -> str:
        """Get MIME type based on file extension."""
        import mimetypes
        mime_type, _ = mimetypes.guess_type(filename)
        return mime_type or "application/octet-stream"


# ============================================================================
# Request/Response Models (Pydantic)
# ============================================================================


class EntityInput(SQLModel):
    """Entity association input for file creation."""
    entity_type: str  # PROJECT, RUN, SAMPLE, QCRECORD
    entity_id: str
    role: str | None = None


class SampleInput(SQLModel):
    """Sample association input for file creation."""
    sample_name: str
    role: str | None = None


class FileCreate(SQLModel):
    """
    Request model for creating a file (upload or reference).
    
    For uploads, file_content is provided separately.
    For external references, just the metadata is needed.
    """
    uri: str  # Required - serves as unique identifier
    original_filename: str | None = None  # For uploads only
    size: int | None = None
    source: str | None = None  # Origin of file record
    created_by: str | None = None
    storage_backend: str | None = None
    entities: List[EntityInput] | None = None
    samples: List[SampleInput] | None = None
    hashes: dict[str, str] | None = None  # {"md5": "abc...", "sha256": "def..."}
    tags: dict[str, str] | None = None  # {"type": "alignment", "format": "bam"}

    model_config = ConfigDict(extra="forbid")


class FileUploadCreate(SQLModel):
    """
    Request model for file upload via form data.
    
    This is a simplified version of FileCreate for form-based uploads
    where files are associated with a single entity.
    """
    filename: str  # Display filename for the upload
    original_filename: str | None = None
    description: str | None = None
    entity_type: str  # PROJECT, RUN
    entity_id: str
    role: str | None = None  # e.g., samplesheet
    is_public: bool = False
    created_by: str | None = None
    relative_path: str | None = None
    overwrite: bool = False

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


class EntityPublic(SQLModel):
    """Public representation of an entity association."""
    entity_type: str
    entity_id: str
    role: str | None


class FilePublic(SQLModel):
    """Public representation of a file."""
    id: uuid.UUID
    uri: str
    filename: str  # Computed from uri
    original_filename: str | None
    size: int | None
    created_on: datetime
    created_by: str | None
    source: str | None
    storage_backend: str | None
    entities: List[EntityPublic]
    samples: List[SamplePublic]
    hashes: List[HashPublic]
    tags: List[TagPublic]


class FileSummary(SQLModel):
    """
    Compact file representation for lists.
    
    Used when embedding files in other responses (e.g., QCRecord).
    """
    id: uuid.UUID
    uri: str
    filename: str  # Computed from uri
    size: int | None
    hashes: List[HashPublic]
    tags: List[TagPublic]
    samples: List[SamplePublic]


class FilesPublic(SQLModel):
    """Paginated list of files."""
    data: List[FilePublic]
    total: int
    page: int
    per_page: int


# ============================================================================
# File Browser Models (for S3/local file listing)
# ============================================================================


class FileBrowserFolder(SQLModel):
    """Folder item for file browser."""
    name: str
    date: str


class FileBrowserFile(SQLModel):
    """File item for file browser."""
    name: str
    date: str
    size: int


class FileBrowserData(SQLModel):
    """File browser data structure with separate folders and files."""
    folders: List[FileBrowserFolder]
    files: List[FileBrowserFile]


# ============================================================================
# Helper Functions
# ============================================================================


def file_to_public(file: File) -> FilePublic:
    """Convert a File model instance to FilePublic response."""
    return FilePublic(
        id=file.id,
        uri=file.uri,
        filename=file.filename,
        original_filename=file.original_filename,
        size=file.size,
        created_on=file.created_on,
        created_by=file.created_by,
        source=file.source,
        storage_backend=file.storage_backend,
        entities=[
            EntityPublic(
                entity_type=e.entity_type,
                entity_id=e.entity_id,
                role=e.role
            ) for e in file.entities
        ],
        samples=[
            SamplePublic(sample_name=s.sample_name, role=s.role)
            for s in file.samples
        ],
        hashes=[
            HashPublic(algorithm=h.algorithm, value=h.value)
            for h in file.hashes
        ],
        tags=[
            TagPublic(key=t.key, value=t.value)
            for t in file.tags
        ],
    )


def file_to_summary(file: File) -> FileSummary:
    """Convert a File model instance to FileSummary response."""
    return FileSummary(
        id=file.id,
        uri=file.uri,
        filename=file.filename,
        size=file.size,
        hashes=[
            HashPublic(algorithm=h.algorithm, value=h.value)
            for h in file.hashes
        ],
        tags=[
            TagPublic(key=t.key, value=t.value)
            for t in file.tags
        ],
        samples=[
            SamplePublic(sample_name=s.sample_name, role=s.role)
            for s in file.samples
        ],
    )
