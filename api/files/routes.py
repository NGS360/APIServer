"""
Routes/endpoints for the Files API
"""

from typing import Optional
from fastapi import APIRouter, Depends, Query, status, Form, UploadFile, File as FastAPIFile
from fastapi.responses import StreamingResponse
import io

from api.files.models import FileBrowserData, FilePublic, EntityType, FileCreate
from api.files import services
from core.deps import get_s3_client, SessionDep

router = APIRouter(prefix="/files", tags=["File Endpoints"])


@router.get("/{file_id}", response_model=FilePublic, tags=["File Endpoints"])
def get_file(
    file_id: str,
    session: SessionDep,
) -> FilePublic:
    """
    Retrieve file metadata by file ID.
    """
    return services.get_file_by_id(session, file_id)


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
    relative_path: Optional[str] = Form(None),
    overwrite: bool = Form(False),
    description: Optional[str] = Form(None),
    is_public: bool = Form(False),
    created_by: Optional[str] = Form(None),
    content: Optional[UploadFile] = FastAPIFile(None),
    s3_client=Depends(get_s3_client),
) -> FilePublic:
    """
    Create a new file record with optional file content upload.
    - **filename**: Name of the file
    - **description**: Optional description of the file
    - **file_type**: Type of file (fastq, bam, vcf, etc.)
    - **entity_type**: Whether this file belongs to a project or run
    - **entity_id**: ID of the project or run this file belongs to
    - **relative_path**: Optional subdirectory path within the entity folder
                         (e.g., "raw_data/sample1" or "results/qc")
    - **overwrite**: If True, replace existing file with same name/location (default: False)
    - **is_public**: Whether the file is publicly accessible
    - **created_by**: User who created the file

    Returns:
        FilePublic with metadata including the assigned file_id

    Raises:
        409 Conflict: If file already exists and overwrite=False

    Examples:
        - File at entity root: relative_path=None
          => s3://bucket/project/P-20260109-0001/abc123_file.txt
        - File in subdirectory: relative_path="raw_data/sample1"
          => s3://bucket/project/P-20260109-0001/raw_data/sample1/abc123_file.txt
    """
    # Create FileCreate object from form data
    file_in = FileCreate(
        filename=filename,
        description=description,
        entity_type=entity_type,
        entity_id=entity_id,
        is_public=is_public,
        created_by=created_by,
        relative_path=relative_path,
        overwrite=overwrite,
    )

    file_content = None
    if content and content.filename:
        file_content = content.file.read()

    return services.create_file(session, s3_client, file_in, file_content)


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
