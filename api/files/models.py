"""
Models for the Files API
"""

from typing import List
import uuid
from datetime import datetime
from enum import Enum
from sqlmodel import SQLModel, Field
from pydantic import ConfigDict


class FileType(str, Enum):
    """File type categories"""

    FASTQ = "fastq"
    BAM = "bam"
    VCF = "vcf"
    SAMPLESHEET = "samplesheet"
    METRICS = "metrics"
    REPORT = "report"
    LOG = "log"
    IMAGE = "image"
    DOCUMENT = "document"
    OTHER = "other"


class EntityType(str, Enum):
    """Entity types that can have files"""

    PROJECT = "project"
    RUN = "run"


class StorageBackend(str, Enum):
    """Storage backend types"""

    LOCAL = "local"
    S3 = "s3"
    AZURE = "azure"
    GCS = "gcs"


class File(SQLModel, table=True):
    """Core file entity that can be associated with runs or projects"""

    __searchable__ = ["filename", "description", "file_id", "destination_uri"]

    id: uuid.UUID | None = Field(default_factory=uuid.uuid4, primary_key=True)
    file_id: str = Field(unique=True, max_length=100)  # Human-readable identifier
    filename: str = Field(max_length=255)
    destination_uri: str = Field(max_length=1024)  # Storage path/URI
    file_path: str = Field(default=None, max_length=1024)  # Actual storage path
    file_size: int | None = None  # Size in bytes
    mime_type: str | None = Field(default=None, max_length=100)
    checksum: str | None = Field(default=None, max_length=64)  # SHA-256 hash

    # Metadata
    upload_date: datetime = Field(default_factory=datetime.utcnow)
    created_by: str | None = Field(default=None, max_length=100)  # User identifier

    model_config = ConfigDict(from_attributes=True)



class FileCreate(SQLModel):
    """Request model for creating a file"""

    filename: str
    destination_uri: str
    created_by: str | None = None

    model_config = ConfigDict(extra="forbid")



class FilePublic(SQLModel):
    """Public file representation"""

    file_id: str
    filename: str
    destination_uri: str
    file_size: int | None
    mime_type: str | None
    upload_date: datetime
    created_by: str | None
    checksum: str | None = None


class FilesPublic(SQLModel):
    """Paginated file listing"""

    data: List[FilePublic]
    total_items: int
    total_pages: int
    current_page: int
    per_page: int
    has_next: bool
    has_prev: bool


class FileUploadRequest(SQLModel):
    """Request model for file upload"""

    filename: str
    description: str | None = None
    file_type: FileType = FileType.OTHER
    is_public: bool = False

    model_config = ConfigDict(extra="forbid")


class FileUploadResponse(SQLModel):
    """Response model for file upload"""

    file_id: str
    filename: str
    file_size: int | None = None
    checksum: str | None = None
    upload_date: datetime
    message: str = "File uploaded successfully"


class FileFilters(SQLModel):
    """File filtering options"""

    entity_type: EntityType | None = None
    entity_id: str | None = None
    file_type: FileType | None = None
    mime_type: str | None = None
    created_by: str | None = None
    is_public: bool | None = None
    is_archived: bool | None = None
    search_query: str | None = None  # Search in filename/description

    model_config = ConfigDict(extra="forbid")


class PaginatedFileResponse(SQLModel):
    """Paginated response for file listings"""

    data: list[FilePublic]
    total_items: int
    total_pages: int
    current_page: int
    per_page: int
    has_next: bool
    has_prev: bool

    model_config = ConfigDict(from_attributes=True)


class FileBrowserFolder(SQLModel):
    """Folder item for file browser"""

    name: str
    date: str


class FileBrowserFile(SQLModel):
    """File item for file browser"""

    name: str
    date: str
    size: int


class FileBrowserData(SQLModel):
    """File browser data structure with separate folders and files"""

    folders: list[FileBrowserFolder]
    files: list[FileBrowserFile]
