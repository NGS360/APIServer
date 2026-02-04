"""
Routes/endpoints for the unified Files API.

Endpoints:
- POST /api/files - Create a new file record (upload or reference)
- GET /api/files/{id} - Get file by UUID
- GET /api/files - List/search files (by URI or entity)
- GET /api/files/{id}/versions - Get all versions of a file
- GET /api/files/list - Browse S3 bucket/folder
- GET /api/files/download - Download file from S3
"""

from typing import Optional
import uuid
from fastapi import APIRouter, Depends, Query, status, Form, UploadFile
from fastapi import File as FastAPIFile
from fastapi.responses import StreamingResponse
import io

from api.files.models import (
    FilePublic,
    FilesPublic,
    FileCreate,
    FileBrowserData,
    file_to_public,
)
from api.files import services
from core.deps import get_s3_client, SessionDep

router = APIRouter(prefix="/files", tags=["File Endpoints"])


@router.post(
    "",
    response_model=FilePublic,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new file record",
)
def create_file(
    session: SessionDep,
    file_create: FileCreate,
) -> FilePublic:
    """
    Create a new file record (external reference).

    This endpoint is for registering files that already exist in storage
    (e.g., pipeline outputs). For file uploads, use the form-data endpoint.

    - **uri**: Required. File location (s3://, file://, etc.)
    - **original_filename**: Optional. Original filename before any renaming
    - **source**: Where this file record originated from
    - **entities**: Entity associations (QCRECORD, SAMPLE, PROJECT, RUN)
    - **samples**: Sample associations with optional roles (tumor/normal)
    - **hashes**: Hash values by algorithm (md5, sha256, etc.)
    - **tags**: Key-value metadata (type, format, description, etc.)

    Note: Same URI can be registered multiple times with different timestamps,
    enabling versioning. Each POST creates a new version.
    """
    file_record = services.create_file(session, file_create)
    return file_to_public(file_record)


@router.post(
    "/upload",
    response_model=FilePublic,
    status_code=status.HTTP_201_CREATED,
    summary="Upload a file",
)
def upload_file(
    session: SessionDep,
    filename: str = Form(...),
    entity_type: str = Form(...),
    entity_id: str = Form(...),
    relative_path: Optional[str] = Form(None),
    overwrite: bool = Form(False),
    description: Optional[str] = Form(None),
    is_public: bool = Form(False),
    created_by: Optional[str] = Form(None),
    role: Optional[str] = Form(None),
    content: Optional[UploadFile] = FastAPIFile(None),
    s3_client=Depends(get_s3_client),
) -> FilePublic:
    """
    Upload a file with optional content.

    - **filename**: Name of the file
    - **entity_type**: Entity type (PROJECT, RUN)
    - **entity_id**: ID of the entity this file belongs to
    - **relative_path**: Optional subdirectory path within entity folder
    - **overwrite**: If True, creates a new version if file exists
    - **description**: Optional file description
    - **is_public**: Whether file is publicly accessible
    - **created_by**: User who uploaded the file
    - **role**: Optional role (e.g., samplesheet)
    - **content**: Optional file content

    Examples:
    - File at entity root: relative_path=None
      => s3://bucket/project/P-123/filename.txt
    - File in subdirectory: relative_path="raw_data/sample1"
      => s3://bucket/project/P-123/raw_data/sample1/filename.txt
    """
    from api.files.models import FileUploadCreate

    file_upload = FileUploadCreate(
        filename=filename,
        description=description,
        entity_type=entity_type.upper(),
        entity_id=entity_id,
        is_public=is_public,
        created_by=created_by,
        relative_path=relative_path,
        overwrite=overwrite,
        role=role,
    )

    file_content = None
    if content and content.filename:
        file_content = content.file.read()

    file_record = services.create_file_upload(
        session, s3_client, file_upload, file_content
    )
    return file_to_public(file_record)


@router.get(
    "",
    response_model=FilesPublic,
    summary="List/search files",
)
def list_files(
    session: SessionDep,
    uri: Optional[str] = Query(
        None,
        description="Filter by URI (returns latest version)"
    ),
    entity_type: Optional[str] = Query(
        None,
        description="Filter by entity type (PROJECT, RUN, SAMPLE, QCRECORD)"
    ),
    entity_id: Optional[str] = Query(
        None,
        description="Filter by entity ID (requires entity_type)"
    ),
    include_archived: bool = Query(
        False,
        description="Include archived files"
    ),
    page: int = Query(1, ge=1, description="Page number"),
    per_page: int = Query(100, ge=1, le=1000, description="Items per page"),
) -> FilesPublic:
    """
    List or search files.

    Filter options:
    - By URI: Returns latest version of the file with that URI
    - By entity: Returns all files associated with the entity

    If no filters provided, returns all files (paginated).
    """
    if uri:
        # Return latest version of specific URI
        file_record = services.get_file_by_uri(session, uri)
        return FilesPublic(
            data=[file_to_public(file_record)],
            total=1,
            page=1,
            per_page=1,
        )

    if entity_type and entity_id:
        # Return files for entity
        files = services.list_files_by_entity(
            session,
            entity_type,
            entity_id,
            include_archived=include_archived,
        )
        # Simple pagination
        start = (page - 1) * per_page
        end = start + per_page
        paginated = files[start:end]
        return FilesPublic(
            data=[file_to_public(f) for f in paginated],
            total=len(files),
            page=page,
            per_page=per_page,
        )

    # TODO: Implement general file listing with pagination
    return FilesPublic(data=[], total=0, page=page, per_page=per_page)


@router.get(
    "/list",
    response_model=FileBrowserData,
    summary="Browse S3 bucket/folder",
)
def browse_s3(
    uri: str = Query(
        ...,
        description="S3 URI to list (e.g., s3://bucket/folder/)"
    ),
    s3_client=Depends(get_s3_client),
) -> FileBrowserData:
    """
    Browse files and folders at the specified S3 URI.

    Returns a list of folders and files at the given path.
    For S3, the full s3:// URI is required.
    """
    return services.list_s3_files(uri=uri, s3_client=s3_client)


@router.get(
    "/download",
    summary="Download file from S3",
)
def download_file(
    path: str = Query(
        ...,
        description="S3 URI of file to download (e.g., s3://bucket/path/file.txt)"
    ),
    s3_client=Depends(get_s3_client),
) -> StreamingResponse:
    """
    Download a file from S3.

    Returns the file as a streaming download with appropriate
    content type and filename.
    """
    file_content, content_type, filename = services.download_file(
        s3_path=path, s3_client=s3_client
    )

    return StreamingResponse(
        io.BytesIO(file_content),
        media_type=content_type,
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"'
        }
    )


@router.get(
    "/{file_id}",
    response_model=FilePublic,
    summary="Get file by UUID",
)
def get_file(
    file_id: uuid.UUID,
    session: SessionDep,
) -> FilePublic:
    """
    Retrieve file metadata by UUID.

    Returns the specific file version identified by the UUID.
    """
    file_record = services.get_file_by_id(session, file_id)
    return file_to_public(file_record)


@router.get(
    "/{file_id}/versions",
    response_model=FilesPublic,
    summary="Get all versions of a file",
)
def get_file_versions(
    file_id: uuid.UUID,
    session: SessionDep,
) -> FilesPublic:
    """
    Get all versions of a file by looking up the URI from the given file_id.

    Returns all versions ordered by created_on descending (newest first).
    """
    # First get the file to find its URI
    file_record = services.get_file_by_id(session, file_id)

    # Then get all versions
    versions = services.get_file_versions(session, file_record.uri)

    return FilesPublic(
        data=[file_to_public(f) for f in versions],
        total=len(versions),
        page=1,
        per_page=len(versions),
    )
