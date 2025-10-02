# Files API Design for NGS360

## Overview
Design a unified Files API that supports file operations (list, fetch, upload, delete) for both sequencing runs and projects, with flexible storage backends and comprehensive metadata tracking.

## Current System Analysis

### Existing Models
- **Projects**: Have `project_id` (string), `name`, and `attributes`
- **Runs**: Have `id` (UUID), `barcode` (computed), `run_folder_uri`, and various metadata
- **Files API**: Currently has skeleton routes but missing models/services

## Proposed Architecture

### 1. Data Model Design

#### Core File Model
```python
class File(SQLModel, table=True):
    """Core file entity that can be associated with runs or projects"""
    
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    file_id: str = Field(unique=True)  # Human-readable identifier
    filename: str = Field(max_length=255)
    original_filename: str = Field(max_length=255)
    file_path: str = Field(max_length=1024)  # Storage path/URI
    file_size: int | None = None  # Size in bytes
    mime_type: str | None = Field(max_length=100)
    checksum: str | None = Field(max_length=64)  # SHA-256 hash
    
    # Metadata
    description: str | None = Field(max_length=1024)
    file_type: FileType = Field(default=FileType.OTHER)
    upload_date: datetime = Field(default_factory=datetime.utcnow)
    created_by: str | None = Field(max_length=100)  # User identifier
    
    # Polymorphic associations
    entity_type: EntityType  # "project" or "run"
    entity_id: str  # project_id or run barcode
    
    # Storage metadata
    storage_backend: StorageBackend = Field(default=StorageBackend.LOCAL)
    is_public: bool = Field(default=False)
    is_archived: bool = Field(default=False)
```

#### Enums
```python
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
```

### 2. API Endpoint Design

#### Unified Files Endpoints
```
# Generic file operations
GET    /api/v1/files                     # List all files (with filters)
POST   /api/v1/files                     # Upload file (requires entity association)
GET    /api/v1/files/{file_id}           # Get file metadata
PUT    /api/v1/files/{file_id}           # Update file metadata
DELETE /api/v1/files/{file_id}           # Delete file
GET    /api/v1/files/{file_id}/download  # Download file content

# Entity-specific file operations
GET    /api/v1/projects/{project_id}/files           # List project files
POST   /api/v1/projects/{project_id}/files           # Upload file to project
GET    /api/v1/projects/{project_id}/files/{file_id} # Get project file

GET    /api/v1/runs/{run_barcode}/files               # List run files
POST   /api/v1/runs/{run_barcode}/files               # Upload file to run
GET    /api/v1/runs/{run_barcode}/files/{file_id}     # Get run file

# Bulk operations
POST   /api/v1/files/bulk-upload         # Upload multiple files
DELETE /api/v1/files/bulk-delete         # Delete multiple files
```

### 3. Request/Response Models

#### File Upload Request
```python
class FileUploadRequest(SQLModel):
    """Request model for file upload"""
    filename: str
    description: str | None = None
    file_type: FileType = FileType.OTHER
    is_public: bool = False
    tags: List[str] | None = None

class FileUploadResponse(SQLModel):
    """Response model for file upload"""
    file_id: str
    filename: str
    upload_url: str | None = None  # For direct upload scenarios
    file_size: int | None = None
    checksum: str | None = None
```

#### File Listing
```python
class FilePublic(SQLModel):
    """Public file representation"""
    file_id: str
    filename: str
    original_filename: str
    file_size: int | None
    mime_type: str | None
    description: str | None
    file_type: FileType
    upload_date: datetime
    created_by: str | None
    entity_type: EntityType
    entity_id: str
    is_public: bool
    download_url: str | None = None

class FilesPublic(SQLModel):
    """Paginated file listing"""
    data: List[FilePublic]
    total_items: int
    total_pages: int
    current_page: int
    per_page: int
    has_next: bool
    has_prev: bool
    filters: Dict[str, Any] | None = None
```

### 4. Storage Strategy

#### Multi-Backend Support
```python
class StorageService:
    """Abstract storage service interface"""
    
    async def upload_file(self, file_data: bytes, file_path: str) -> str:
        """Upload file and return storage URI"""
        pass
    
    async def download_file(self, file_path: str) -> bytes:
        """Download file content"""
        pass
    
    async def delete_file(self, file_path: str) -> bool:
        """Delete file from storage"""
        pass
    
    async def get_download_url(self, file_path: str, expires_in: int = 3600) -> str:
        """Generate temporary download URL"""
        pass

class LocalStorageService(StorageService):
    """Local filesystem storage"""
    pass

class S3StorageService(StorageService):
    """AWS S3 storage"""
    pass
```

#### File Path Strategy
```
Storage Structure:
/{storage_root}/
  /projects/
    /{project_id}/
      /{file_type}/
        /{year}/{month}/
          /{file_id}_{original_filename}
  /runs/
    /{run_barcode}/
      /{file_type}/
        /{year}/{month}/
          /{file_id}_{original_filename}
```

### 5. Advanced Features

#### File Filtering and Search
```python
class FileFilters(SQLModel):
    """File filtering options"""
    entity_type: EntityType | None = None
    entity_id: str | None = None
    file_type: FileType | None = None
    mime_type: str | None = None
    created_by: str | None = None
    date_from: datetime | None = None
    date_to: datetime | None = None
    is_public: bool | None = None
    is_archived: bool | None = None
    tags: List[str] | None = None
    search_query: str | None = None  # Search in filename/description
```

#### File Versioning (Future Enhancement)
```python
class FileVersion(SQLModel, table=True):
    """File version tracking"""
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    file_id: uuid.UUID = Field(foreign_key="file.id")
    version_number: int
    file_path: str
    file_size: int
    checksum: str
    created_date: datetime = Field(default_factory=datetime.utcnow)
    is_current: bool = Field(default=True)
```

### 6. Security and Access Control

#### File Access Permissions
```python
class FilePermission(SQLModel, table=True):
    """File-level permissions"""
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    file_id: uuid.UUID = Field(foreign_key="file.id")
    user_id: str | None = None
    group_id: str | None = None
    permission_type: PermissionType
    granted_date: datetime = Field(default_factory=datetime.utcnow)

class PermissionType(str, Enum):
    READ = "read"
    WRITE = "write"
    DELETE = "delete"
    ADMIN = "admin"
```

### 7. Integration Points

#### With Existing Models
- **Projects**: Add relationship to files via `entity_id` = `project_id`
- **Runs**: Add relationship to files via `entity_id` = `run.barcode`
- **Search**: Include files in OpenSearch indexing for full-text search

#### Database Relationships
```python
# In Project model
files: List["File"] = Relationship(
    sa_relationship_kwargs={
        "primaryjoin": "and_(Project.project_id == File.entity_id, File.entity_type == 'project')",
        "foreign_keys": "[File.entity_id]"
    }
)

# In SequencingRun model  
files: List["File"] = Relationship(
    sa_relationship_kwargs={
        "primaryjoin": "and_(SequencingRun.barcode == File.entity_id, File.entity_type == 'run')",
        "foreign_keys": "[File.entity_id]"
    }
)
```

## Implementation Plan

### Phase 1: Core Infrastructure
1. Create file models and enums
2. Implement basic storage service (local filesystem)
3. Create core CRUD operations
4. Add database migration

### Phase 2: API Endpoints
1. Implement generic file endpoints
2. Add entity-specific endpoints
3. Create file upload/download functionality
4. Add comprehensive error handling

### Phase 3: Advanced Features
1. Add file filtering and search
2. Implement multiple storage backends
3. Add file metadata extraction
4. Create bulk operations

### Phase 4: Integration & Security
1. Integrate with existing project/run models
2. Add authentication and authorization
3. Implement file permissions
4. Add audit logging

## Benefits

1. **Unified Interface**: Single API for all file operations across projects and runs
2. **Flexible Storage**: Support for multiple storage backends (local, S3, etc.)
3. **Rich Metadata**: Comprehensive file metadata and categorization
4. **Scalable**: Designed to handle large numbers of files efficiently
5. **Secure**: Built-in permission system and access controls
6. **Searchable**: Integration with existing search infrastructure
7. **Extensible**: Easy to add new file types and storage backends

## Example Usage

```python
# Upload a file to a project
POST /api/v1/projects/PROJ001/files
{
    "filename": "analysis_results.pdf",
    "description": "Final analysis report",
    "file_type": "report",
    "is_public": false
}

# List all FASTQ files for a run
GET /api/v1/runs/190110_MACHINE123_0001_FLOWCELL123/files?file_type=fastq

# Search for files across all entities
GET /api/v1/files?search_query=analysis&file_type=report&date_from=2024-01-01
```

This design provides a robust, scalable, and flexible file management system that integrates seamlessly with the existing NGS360 architecture.