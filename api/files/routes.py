"""
Routes/endpoints for the Files API
"""

from typing import Optional
from fastapi import APIRouter, Query, HTTPException, status, UploadFile, File as FastAPIFile
from fastapi.responses import StreamingResponse
from core.deps import SessionDep
from api.files.models import (
    FileCreate,
    FileUpdate,
    FilePublic,
    PaginatedFileResponse,
    FileFilters,
    FileType,
    EntityType,
)
import api.files.services as services

router = APIRouter(prefix="/files", tags=["Files"])


@router.post(
    "",
    response_model=FilePublic,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new file record"
)
def create_file(
    session: SessionDep,
    file_in: FileCreate,
    content: Optional[UploadFile] = FastAPIFile(None)
) -> FilePublic:
    """
    Create a new file record with optional file content upload.
    
    - **filename**: Name of the file
    - **description**: Optional description of the file
    - **file_type**: Type of file (fastq, bam, vcf, etc.)
    - **entity_type**: Whether this file belongs to a project or run
    - **entity_id**: ID of the project or run this file belongs to
    - **is_public**: Whether the file is publicly accessible
    - **created_by**: User who created the file
    """
    file_content = None
    if content and content.filename:
        file_content = content.file.read()
    
    return services.create_file(session, file_in, file_content)


@router.get(
    "",
    response_model=PaginatedFileResponse,
    summary="List files with filtering and pagination"
)
def list_files(
    session: SessionDep,
    page: int = Query(1, ge=1, description="Page number (1-indexed)"),
    per_page: int = Query(20, ge=1, le=100, description="Number of items per page"),
    entity_type: Optional[EntityType] = Query(None, description="Filter by entity type"),
    entity_id: Optional[str] = Query(None, description="Filter by entity ID"),
    file_type: Optional[FileType] = Query(None, description="Filter by file type"),
    search: Optional[str] = Query(None, description="Search in filename and description"),
    is_public: Optional[bool] = Query(None, description="Filter by public/private status"),
    created_by: Optional[str] = Query(None, description="Filter by creator"),
) -> PaginatedFileResponse:
    """
    Get a paginated list of files with optional filtering.
    
    Supports filtering by:
    - Entity type and ID (project or run)
    - File type (fastq, bam, vcf, etc.)
    - Public/private status
    - Creator
    - Text search in filename and description
    """
    filters = FileFilters(
        entity_type=entity_type,
        entity_id=entity_id,
        file_type=file_type,
        search_query=search,
        is_public=is_public,
        created_by=created_by,
    )
    
    return services.list_files(session, filters, page, per_page)


@router.get(
    "/{file_id}",
    response_model=FilePublic,
    summary="Get file by ID"
)
def get_file(
    session: SessionDep,
    file_id: str
) -> FilePublic:
    """
    Get a single file by its file_id.
    
    - **file_id**: The unique file identifier
    """
    try:
        return services.get_file(session, file_id)
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"File with id {file_id} not found"
        )


@router.put(
    "/{file_id}",
    response_model=FilePublic,
    summary="Update file metadata"
)
def update_file(
    session: SessionDep,
    file_id: str,
    file_update: FileUpdate
) -> FilePublic:
    """
    Update file metadata.
    
    - **file_id**: The unique file identifier
    - **file_update**: Fields to update
    """
    try:
        return services.update_file(session, file_id, file_update)
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"File with id {file_id} not found"
        )


@router.delete(
    "/{file_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete file"
)
def delete_file(
    session: SessionDep,
    file_id: str
) -> None:
    """
    Delete a file and its content.
    
    - **file_id**: The unique file identifier
    """
    try:
        success = services.delete_file(session, file_id)
        if not success:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"File with id {file_id} not found"
            )
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"File with id {file_id} not found"
        )


@router.get(
    "/{file_id}/content",
    summary="Download file content"
)
def download_file(
    session: SessionDep,
    file_id: str
):
    """
    Download the content of a file.
    
    - **file_id**: The unique file identifier
    """
    try:
        # Get file metadata
        file_record = services.get_file(session, file_id)
        
        # Get file content
        content = services.get_file_content(session, file_id)
        
        # Create streaming response
        def generate():
            yield content
        
        return StreamingResponse(
            generate(),
            media_type=file_record.mime_type or "application/octet-stream",
            headers={
                "Content-Disposition": f"attachment; filename={file_record.filename}"
            }
        )
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"File with id {file_id} not found or content not available"
        )


@router.post(
    "/{file_id}/content",
    response_model=FilePublic,
    summary="Upload file content"
)
def upload_file_content(
    session: SessionDep,
    file_id: str,
    content: UploadFile = FastAPIFile(...)
) -> FilePublic:
    """
    Upload content for an existing file record.
    
    - **file_id**: The unique file identifier
    - **content**: The file content to upload
    """
    try:
        file_content = content.file.read()
        return services.update_file_content(session, file_id, file_content)
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"File with id {file_id} not found"
        )


@router.get(
    "/entity/{entity_type}/{entity_id}",
    response_model=PaginatedFileResponse,
    summary="List files for a specific entity"
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
    
    - **entity_type**: Either "project" or "run"
    - **entity_id**: The project ID or run barcode
    """
    filters = FileFilters(
        entity_type=entity_type,
        entity_id=entity_id,
        file_type=file_type,
    )
    
    return services.list_files_for_entity(session, entity_type, entity_id, page, per_page, filters)


@router.get(
    "/entity/{entity_type}/{entity_id}/count",
    summary="Get file count for entity"
)
def get_file_count_for_entity(
    session: SessionDep,
    entity_type: EntityType,
    entity_id: str
) -> dict:
    """
    Get the total number of files for a specific project or run.
    
    - **entity_type**: Either "project" or "run"
    - **entity_id**: The project ID or run barcode
    """
    count = services.get_file_count_for_entity(session, entity_type, entity_id)
    return {"entity_type": entity_type, "entity_id": entity_id, "file_count": count}
