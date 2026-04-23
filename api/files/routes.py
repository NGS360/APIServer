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
from fastapi.responses import RedirectResponse

from api.files.models import FileUploadCreate

from api.files.models import (
    FilePublic,
    FilesPublic,
    FileCreate,
    FileUpdate,
    FileBrowserData,
    file_to_public,
)
from api.files import services
from api.auth.deps import CurrentSuperuser
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
    - **project_id**: Project business key (string)
    - **sequencing_run_id**: SequencingRun UUID
    - **qcrecord_id**: QCRecord UUID
    - **workflow_run_id**: WorkflowRun UUID
    - **pipeline_id**: Pipeline UUID
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
    project_id: Optional[str] = Form(None, description="Project business key"),
    sequencing_run_id: Optional[uuid.UUID] = Form(None, description="SequencingRun UUID"),
    qcrecord_id: Optional[uuid.UUID] = Form(None, description="QCRecord UUID"),
    workflow_run_id: Optional[uuid.UUID] = Form(None, description="WorkflowRun UUID"),
    pipeline_id: Optional[uuid.UUID] = Form(None, description="Pipeline UUID"),
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
    - **project_id**: Project business key (exactly one entity ID required)
    - **sequencing_run_id**: SequencingRun UUID
    - **qcrecord_id**: QCRecord UUID
    - **workflow_run_id**: WorkflowRun UUID
    - **pipeline_id**: Pipeline UUID
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

    file_upload = FileUploadCreate(
        filename=filename,
        description=description,
        project_id=project_id,
        sequencing_run_id=sequencing_run_id,
        qcrecord_id=qcrecord_id,
        workflow_run_id=workflow_run_id,
        pipeline_id=pipeline_id,
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
        description=(
            "Filter by entity type "
            "(PROJECT, RUN, SEQUENCING_RUN, SAMPLE, QCRECORD, WORKFLOW_RUN, PIPELINE)"
        )
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
    responses={307: {"description": "Redirect to presigned S3 URL"}},
)
def download_file(
    path: str = Query(
        ...,
        description="S3 URI of file to download (e.g., s3://bucket/path/file.txt)"
    ),
    s3_client=Depends(get_s3_client),
):
    """
    Download a file from S3 via presigned URL redirect.

    Returns a 307 redirect to a time-limited presigned S3 URL.
    The client follows the redirect to download directly from S3,
    offloading bandwidth from the API server.
    """
    presigned_url = services.generate_presigned_url(
        s3_path=path, s3_client=s3_client
    )
    return RedirectResponse(url=presigned_url, status_code=307)


@router.patch(
    "/{file_id}",
    response_model=FilePublic,
    summary="Update a file record (superuser only)",
)
def update_file(
    file_id: uuid.UUID,
    session: SessionDep,
    file_update: FileUpdate,
    current_user: CurrentSuperuser,
) -> FilePublic:
    """
    Update scalar fields on a file record.

    Only fields included in the request body are updated; all others
    (including entity associations, hashes, tags, and samples) remain
    unchanged.

    **Primary use case:** correcting a URI (e.g., wrong S3 bucket).

    Requires superuser privileges.
    """
    file_record = services.update_file(session, file_id, file_update)
    return file_to_public(file_record)


@router.delete(
    "/{file_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a file record (superuser only)",
)
def delete_file(
    file_id: uuid.UUID,
    session: SessionDep,
    current_user: CurrentSuperuser,
) -> None:
    """
    Hard-delete a file record and all associated child rows.

    Cascade-deletes: FileHash, FileTag, FileSample, FileProject,
    FileSequencingRun, FileQCRecord, FileWorkflowRun, FilePipeline.

    **This action is irreversible.**

    Requires superuser privileges.
    """
    services.delete_file(session, file_id)


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
