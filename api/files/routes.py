"""
Routes/endpoints for the Files API
"""
from typing import Optional
import io

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from fastapi import (
    APIRouter,
    Query,
    HTTPException,
    status,
    UploadFile,
    File as FastAPIFile,
    Form,
)

from core.deps import get_s3_client, SessionDep
from api.files.models import (
    FileCreate,
    FileUpdate,
    FilePublic,
    PaginatedFileResponse,
    FileFilters,
    FileType,
    EntityType,
    FileBrowserData,
)
from api.files import services

router = APIRouter(prefix="/files", tags=["Files"])


@router.post(
    "",
    response_model=FilePublic,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new file record",
)
def create_file(
    session: SessionDep,
    filename: str = Form(...),
    entity_type: EntityType = Form(...),
    entity_id: str = Form(...),
    description: Optional[str] = Form(None),
    file_type: FileType = Form(FileType.OTHER),
    is_public: bool = Form(False),
    created_by: Optional[str] = Form(None),
    content: Optional[UploadFile] = FastAPIFile(None),
    s3_client=Depends(get_s3_client),
) -> FilePublic:
    """
    Create a new file record with optional file content upload.

    Storage backend (S3 vs Local) is automatically determined based on
    configuration and entity type.

    - **filename**: Name of the file
    - **description**: Optional description of the file
    - **file_type**: Type of file (fastq, bam, vcf, etc.)
    - **entity_type**: Whether this file belongs to a project or run
    - **entity_id**: ID of the project or run this file belongs to
    - **is_public**: Whether the file is publicly accessible
    - **created_by**: User who created the file
    """
    # Create FileCreate object from form data
    file_in = FileCreate(
        filename=filename,
        description=description,
        file_type=file_type,
        entity_type=entity_type,
        entity_id=entity_id,
        is_public=is_public,
        created_by=created_by,
    )

    file_content = None
    if content and content.filename:
        file_content = content.file.read()

    return services.create_file(session, file_in, file_content, s3_client=s3_client)


@router.get(
    "/browse", response_model=FileBrowserData, summary="Browse filesystem directory"
)
def browse_filesystem(
    directory_path: str = Query(
        "", description="Directory path to browse (local path or s3://bucket/key)"
    ),
    storage_root: str = Query(
        "storage", description="Storage root directory (ignored for S3 paths)"
    ),
) -> FileBrowserData:
    """
    Browse a filesystem directory or S3 bucket and return folders and files in structured format.

    Supports both local filesystem and AWS S3:
    - **Local paths**: Relative to storage_root (empty for root) or absolute paths
    - **S3 paths**: Use s3://bucket/key format (e.g., s3://my-bucket/path/to/folder/)
    - **storage_root**: Base storage directory for local paths (ignored for S3)

    Returns separate arrays for folders and files with name, date, and size information.

    For S3 paths:
    - Requires AWS credentials to be configured
    - Folders represent S3 prefixes (common prefixes)
    - Files show S3 object metadata (size, last modified)

    Examples:
    - Local: `/browse?directory_path=project1/data`
    - S3: `/browse?directory_path=s3://my-bucket/project1/data/`
    """
    return services.browse_filesystem(directory_path, storage_root)


@router.get(
    "/browse-db",
    response_model=FileBrowserData,
    summary="List database files in browser format",
)
def list_files_browser_format(
    session: SessionDep,
    page: int = Query(1, ge=1, description="Page number (1-indexed)"),
    per_page: int = Query(20, ge=1, le=100, description="Number of items per page"),
    entity_type: Optional[EntityType] = Query(
        None, description="Filter by entity type"
    ),
    entity_id: Optional[str] = Query(None, description="Filter by entity ID"),
    file_type: Optional[FileType] = Query(None, description="Filter by file type"),
    search: Optional[str] = Query(
        None, description="Search in filename and description"
    ),
    is_public: Optional[bool] = Query(
        None, description="Filter by public/private status"
    ),
    created_by: Optional[str] = Query(None, description="Filter by creator"),
) -> FileBrowserData:
    """
    Get database files in FileBrowserData format (files only, no folders).

    This endpoint returns the same file data as the regular list_files endpoint,
    but formatted to match the FileBrowserData structure with separate folders and files arrays.
    Since database files don't have folder structure, the folders array will be empty.
    """
    filters = FileFilters(
        entity_type=entity_type,
        entity_id=entity_id,
        file_type=file_type,
        search_query=search,
        is_public=is_public,
        created_by=created_by,
    )

    return services.list_files_as_browser_data(session, filters, page, per_page)


@router.get("/{file_id}", response_model=FilePublic, summary="Get file by ID")
def get_file(session: SessionDep, file_id: str) -> FilePublic:
    """
    Get a single file by its file_id.

    - **file_id**: The unique file identifier
    """
    try:
        return services.get_file(session, file_id)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"File with id {file_id} not found",
        ) from exc


@router.put("/{file_id}", response_model=FilePublic, summary="Update file metadata")
def update_file(
    session: SessionDep, file_id: str, file_update: FileUpdate
) -> FilePublic:
    """
    Update file metadata.

    - **file_id**: The unique file identifier
    - **file_update**: Fields to update
    """
    try:
        return services.update_file(session, file_id, file_update)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"File with id {file_id} not found",
        ) from exc


@router.delete(
    "/{file_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Delete file"
)
def delete_file(
    session: SessionDep, file_id: str, s3_client=Depends(get_s3_client)
) -> None:
    """
    Delete a file and its content from storage (local or S3).

    - **file_id**: The unique file identifier
    """
    try:
        success = services.delete_file(session, file_id, s3_client=s3_client)
        if not success:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"File with id {file_id} not found",
            )
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"File with id {file_id} not found",
        ) from exc


@router.post(
    "/{file_id}/content", response_model=FilePublic, summary="Upload file content"
)
def upload_file_content(
    session: SessionDep,
    file_id: str,
    content: UploadFile = FastAPIFile(...),
    s3_client=Depends(get_s3_client),
) -> FilePublic:
    """
    Upload content for an existing file record.
    
    Updates file in appropriate storage backend (S3 or local).

    - **file_id**: The unique file identifier
    - **content**: The file content to upload
    """
    try:
        file_content = content.file.read()
        return services.update_file_content(
            session, file_id, file_content, s3_client=s3_client
        )
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"File with id {file_id} not found",
        ) from exc


@router.get(
    "/entity/{entity_type}/{entity_id}",
    response_model=PaginatedFileResponse,
    summary="List files for a specific entity.",
)
def list_files_for_entity(
    session: SessionDep,
    entity_type: EntityType,
    entity_id: str,
    page: int = Query(1, ge=1, description="Page number (1-indexed)"),
    per_page: int = Query(20, ge=1, le=100, description="Number of items per page"),
    file_type: Optional[FileType] = Query(None, description="Filter by file type"),
) -> PaginatedFileResponse:
    """
    Get all files associated with a specific project or run.
    This is the same as /api/v1/files, but scoped to a specific entity.

    - **entity_type**: Either "project" or "run"
    - **entity_id**: The project ID or run barcode
    """
    return services.list_files_for_entity(
        session, entity_type, entity_id, page, per_page, file_type
    )


@router.get(
    "/entity/{entity_type}/{entity_id}/count", summary="Get file count for entity"
)
def get_file_count_for_entity(
    session: SessionDep, entity_type: EntityType, entity_id: str
) -> dict:
    """
    Get the total number of files for a specific project or run.

    - **entity_type**: Either "project" or "run"
    - **entity_id**: The project ID or run barcode
    """
    count = services.get_file_count_for_entity(session, entity_type, entity_id)
    return {"entity_type": entity_type, "entity_id": entity_id, "file_count": count}


@router.get("/list", response_model=FileBrowserData, tags=["File Endpoints"])
def list_files(
    uri: str = Query(
        ...,
        description="URI to list (e.g., s3://bucket/folder/)"
    ),
    s3_client=Depends(get_s3_client),
) -> FileBrowserData:
    """
    Browse files and folders at the specified URI.

    For S3:
    - Full s3:// URI is required
    - No navigation outside the initial uri is allowed
    """
    return services.list_files(uri=uri, s3_client=s3_client)


@router.get("/download", tags=["File Endpoints"])
def download_file(
    path: str = Query(
        ...,
        description="S3 URI of the file to download (e.g., s3://bucket/path/file.txt)"
    ),
    s3_client=Depends(get_s3_client),
) -> StreamingResponse:
    """
    Download a file from S3.

    Returns the file as a streaming download with appropriate content type and filename.

    Args:
        path: Full S3 URI to the file (e.g., s3://bucket/folder/file.txt)

    Returns:
        StreamingResponse with the file content
    """
    file_content, content_type, filename = services.download_file(
        s3_path=path, s3_client=s3_client
    )

    # Create a streaming response with the file content
    return StreamingResponse(
        io.BytesIO(file_content),
        media_type=content_type,
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"'
        }
    )
