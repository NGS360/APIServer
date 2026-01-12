"""
Models for the Files API
"""
from datetime import datetime, timezone
from enum import Enum
import hashlib
import uuid
from sqlmodel import Field, SQLModel
from pydantic import ConfigDict


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

    __searchable__ = ["filename", "description", "file_id"]

    id: uuid.UUID | None = Field(default_factory=uuid.uuid4, primary_key=True)
    file_id: str = Field(unique=True, max_length=100)  # Human-readable identifier
    filename: str = Field(max_length=255)
    original_filename: str = Field(max_length=255)
    file_path: str = Field(max_length=1024)  # Storage path/URI
    file_size: int | None = None  # Size in bytes
    mime_type: str | None = Field(default=None, max_length=100)
    checksum: str | None = Field(default=None, max_length=64)  # SHA-256 hash

    # Metadata
    description: str | None = Field(default=None, max_length=1024)
    upload_date: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    created_by: str | None = Field(default=None, max_length=100)  # User identifier

    # Polymorphic associations
    entity_type: EntityType  # "project" or "run"
    entity_id: str = Field(max_length=100)  # project_id or run barcode

    # Storage metadata
    storage_backend: StorageBackend = Field(default=StorageBackend.LOCAL)
    is_public: bool = Field(default=False)
    is_archived: bool = Field(default=False)

    # Subdirectory path within entity folder
    relative_path: str | None = Field(default=None, max_length=1024)

    model_config = ConfigDict(from_attributes=True)

    @staticmethod
    def generate_file_id() -> str:
        """Generate a unique file ID"""
        import secrets
        import string

        alphabet = string.ascii_letters + string.digits
        return "".join(secrets.choice(alphabet) for _ in range(12))

    @staticmethod
    def generate_file_path(
        entity_type: EntityType,
        entity_id: str,
        filename: str,
        relative_path: str | None = None,
    ) -> str:
        """
        Generate a structured file path.

        Args:
            entity_type: Type of entity (project or run)
            entity_id: ID of the entity
            filename: Name of the file (usually includes file_id prefix)
            relative_path: Optional subdirectory path (e.g., "raw_data/sample1")

        Returns:
            Relative path string (without storage root)

        Examples:
            generate_file_path("project", "P-20260109-0001", "abc123_file.txt")
            => "project/P-20260109-0001/abc123_file.txt"

            generate_file_path("project", "P-20260109-0001", "abc123_file.txt", "raw_data/sample1")
            => "project/P-20260109-0001/raw_data/sample1/abc123_file.txt"
        """
        # Build path components
        path_parts = [entity_type.value, entity_id]

        # Add subdirectory if provided
        if relative_path:
            # Normalize: remove leading/trailing slashes, handle empty string
            normalized = relative_path.strip('/')
            if normalized:
                path_parts.append(normalized)

        # Add filename
        path_parts.append(filename)

        # Join with forward slashes (S3 standard)
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

        # Remove leading/trailing slashes
        path = relative_path.strip('/')

        if not path:
            return None

        # Security checks
        if '..' in path:
            raise ValueError("Path traversal not allowed (..)")

        if path.startswith('/'):
            raise ValueError("Absolute paths not allowed")

        # Check for double slashes
        if '//' in path:
            raise ValueError("Double slashes not allowed")

        # Optional: validate characters (allow alphanumeric, dash, underscore, slash)
        import re
        if not re.match(r'^[a-zA-Z0-9_\-/]+$', path):
            raise ValueError(
                "Invalid characters in path. "
                "Only alphanumeric, dash, underscore, and forward slash allowed"
            )

        return path

    @staticmethod
    def calculate_file_checksum(file_content: bytes) -> str:
        """Calculate SHA-256 checksum of file content"""
        return hashlib.sha256(file_content).hexdigest()

    @staticmethod
    def get_mime_type(filename: str) -> str:
        """Get MIME type based on file extension"""
        import mimetypes

        mime_type, _ = mimetypes.guess_type(filename)
        return mime_type or "application/octet-stream"


class FileCreate(SQLModel):
    """Request model for creating a file"""

    filename: str
    original_filename: str | None = None
    description: str | None = None
    entity_type: EntityType
    entity_id: str
    is_public: bool = False
    created_by: str | None = None
    relative_path: str | None = None
    overwrite: bool = False

    model_config = ConfigDict(extra="forbid")


class FilePublic(SQLModel):
    """Public file representation"""

    file_id: str
    filename: str
    original_filename: str
    file_size: int | None
    mime_type: str | None
    description: str | None
    upload_date: datetime
    created_by: str | None
    entity_type: EntityType
    entity_id: str
    is_public: bool
    is_archived: bool
    storage_backend: StorageBackend
    checksum: str | None = None
    relative_path: str | None = None


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
