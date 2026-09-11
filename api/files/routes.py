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

from fastapi import (APIRouter, Depends, Form, HTTPException, Query, Request,
                     Response, UploadFile, status)
from fastapi import File as FastAPIFile
from fastapi.responses import RedirectResponse
from pydantic import ValidationError
from sqlmodel import col, select

from api.files.models import FileUploadCreate

from api.files.models import (
    FilePublic,
    FilesPublic,
    FileCreate,
    FileUpdate,
    FileBrowserData,
    PresignedDownload,
    file_to_public,
)
from api.files import services
from api.auth.deps import CurrentSuperuser, OptionalUser
from api.files.scope import scope_for_uri
from api.rbac.deps import AuthzDep, decide, require_permission
from api.rbac.permissions import Permission
from core.deps import get_s3_client, SessionDep

router = APIRouter(prefix="/files", tags=["File Endpoints"])


@router.post(
    "",
    response_model=FilePublic,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new file record",
    dependencies=[Depends(require_permission(Permission.FILE_CREATE))],
)
def create_file(
    session: SessionDep,
    file_create: FileCreate,
    current_user: OptionalUser = None,
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
    - **pipeline_id**: Pipeline UUID
    - **samples**: Sample associations with optional roles (tumor/normal)
    - **hashes**: Hash values by algorithm (md5, sha256, etc.)
    - **tags**: Key-value metadata (type, format, description, etc.)
    - **created_by**: Optional. The person the file belongs to, which for
      pipeline registrations is the scientist the work was done for rather
      than the caller. Must name a known NGS360 account.

    The authenticated caller is recorded separately as **submitted_by** and
    cannot be set by the client.

    Note: Same URI can be registered multiple times with different timestamps,
    enabling versioning. Each POST creates a new version.
    """
    file_record = services.create_file(
        session,
        file_create,
        submitted_by=current_user.username if current_user else None,
    )
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
    pipeline_id: Optional[uuid.UUID] = Form(None, description="Pipeline UUID"),
    relative_path: Optional[str] = Form(None),
    overwrite: bool = Form(False),
    description: Optional[str] = Form(None),
    is_public: bool = Form(False),
    created_by: Optional[str] = Form(None),
    role: Optional[str] = Form(None),
    content: Optional[UploadFile] = FastAPIFile(None),
    s3_client=Depends(get_s3_client),
    current_user: OptionalUser = None,
) -> FilePublic:
    """
    Upload a file with optional content.

    - **filename**: Name of the file
    - **project_id**: Project business key (exactly one entity ID required)
    - **sequencing_run_id**: SequencingRun UUID
    - **qcrecord_id**: QCRecord UUID
    - **pipeline_id**: Pipeline UUID
    - **relative_path**: Optional subdirectory path within entity folder
    - **overwrite**: If True, creates a new version if file exists
    - **description**: Optional file description
    - **is_public**: Whether file is publicly accessible
    - **created_by**: Optional. The person the file belongs to, which need not
      be the caller. Must name a known NGS360 account. The authenticated
      caller is recorded separately as **submitted_by**.
    - **role**: Optional role (e.g., samplesheet)
    - **content**: Optional file content

    Examples:
    - File at entity root: relative_path=None
      => s3://bucket/project/P-123/filename.txt
    - File in subdirectory: relative_path="raw_data/sample1"
      => s3://bucket/project/P-123/raw_data/sample1/filename.txt
    """

    try:
        file_upload = FileUploadCreate(
            filename=filename,
            description=description,
            project_id=project_id,
            sequencing_run_id=sequencing_run_id,
            qcrecord_id=qcrecord_id,
            pipeline_id=pipeline_id,
            is_public=is_public,
            created_by=created_by,
            relative_path=relative_path,
            overwrite=overwrite,
            role=role,
        )
    except ValidationError as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=e.errors(),
        )

    file_content = None
    if content and content.filename:
        file_content = content.file.read()

    file_record = services.create_file_upload(
        session,
        s3_client,
        file_upload,
        file_content,
        submitted_by=current_user.username if current_user else None,
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


def _restricted_projects(session, project_ids) -> list:
    """Which of these projects have opted out of open downloads."""
    if not project_ids:
        return []
    from api.project.models import Project

    return list(
        session.exec(
            select(Project.id).where(
                col(Project.id).in_(list(project_ids)),
                Project.download_restricted.is_(True),
            )
        ).all()
    )


def require_file_download(
    request: Request,
    authz: AuthzDep,
    session: SessionDep,
    path: str = Query(..., description="S3 URI of the file"),
):
    """
    May this caller download *this* file? Open unless the project says otherwise.

    Downloads are open to any authenticated caller. A project opts out by setting
    `download_restricted`, and only then is `file:download` consulted. Absence of
    a restriction is permission -- see docs/RBAC.md, "Downloads: open by default,
    restricted by exception".

    The parameter is a URI rather than a project id, so the project still has to
    be resolved before its restriction can be read -- api/files/scope.py does
    that. The resolver is unchanged by the policy inversion; it just answers a
    different question now. Previously "which project must the caller belong
    to?", now "which project's restriction applies?".

    Three cases:

    - **Resolved and unrestricted.** Allowed, without consulting any permission.
      This is the common path and the reason the policy changed: one genomics
      workload read 66 projects 33M times in a month, and requiring a grant per
      project made project membership mean "reads everything".

    - **Resolved and restricted.** Requires `file:download` on the project plane,
      which project_viewer and above carry -- so a restricted project's members
      are its allowlist. `has_in_project` also honours a *global* grant, so
      lab_manager, auditor, admin and superusers pass regardless. That is
      intended for cross-project operation, and it is exactly why `member` must
      **not** be given global `file:download`: it would satisfy every restriction
      for every user and make this branch unreachable.

    - **Unresolved.** Requires *global* `file:download`, unchanged. "Belongs to
      no project" is not evidence of permission, and this case is load-bearing
      for a reason beyond authorization: generate_presigned_url signs whatever
      bucket and key it is handed, so an unresolved URI can name any object the
      API's own IAM role can read. Keeping it privileged is what stops the
      endpoint being an arbitrary-S3-read proxy. Do not "simplify" this to allow.

    A dependency may take the same query parameter as its handler; both receive it
    and the OpenAPI schema is unchanged.
    """
    scope = scope_for_uri(session, path)
    if scope.resolved:
        restricted = _restricted_projects(session, scope.project_ids)
        if not restricted:
            granted = True
        else:
            # Every restricted project in the set has to be satisfied. Only one
            # project is ever resolved in practice -- measured 0 multi-project
            # files in production -- so this is the safe reading of a case that
            # does not currently occur, not a considered conflict policy.
            granted = all(
                authz.has_in_project(Permission.FILE_DOWNLOAD, project_id)
                for project_id in restricted
            )
    else:
        granted = authz.has(Permission.FILE_DOWNLOAD)

    # The origin is on the decision record so the mix of project-, sample- and
    # run-resolved downloads is measurable, and so the unregistered surface can be
    # sized before anyone proposes tightening the fallback above.
    # The URI goes on the record as the subject. Without it a refusal reading
    # "unregistered, 0 projects" cannot be told apart from a resolver that failed
    # to match a URI it should have -- which is the difference between "register
    # these files" and "fix this code".
    decide(request, granted, (Permission.FILE_DOWNLOAD,),
           scope=f"file via {scope.origin}, {len(scope.project_ids)} project(s)",
           subject=path)
    return authz


require_file_download.rbac_permissions = (Permission.FILE_DOWNLOAD,)
require_file_download.rbac_plane = "project"


@router.get(
    "/download",
    summary="Download file from S3",
    responses={307: {"description": "Redirect to presigned S3 URL"}},
    dependencies=[Depends(require_file_download)],
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

    Guarded, as of 2026-09-09, by the same check as GET /files/download-url. The
    response is unchanged -- still a 307 to S3 -- so every client that already
    sends credentials is unaffected. What changes is that anonymous callers now
    get 401, and a file in a restricted project gets 403.

    An earlier version of this docstring said the route *could not* be guarded,
    because the UI used it as a plain link and a browser following a link cannot
    send an Authorization header. That was true when written and is no longer:
    the frontend fetches GET /files/download-url with its token and navigates to
    the returned URL itself (src/lib/download.ts), and the built bundle contains
    no reference to this route at all. Measured browser traffic over the 30 days
    to 2026-09-09 was 41 requests -- 39 of them one bulk download on 08-15, most
    likely from a tab holding a pre-fix bundle, then 2 on 09-04 and none since.

    Still deprecated in favour of GET /files/download-url, which returns the URL
    as JSON rather than as a redirect. This route stays because ~1.1M requests a
    day arrive on it from htslib, and it now enforces the same policy, so there
    is no longer any urgency to move them.
    """
    presigned_url = services.generate_presigned_url(
        s3_path=path, s3_client=s3_client
    )
    return RedirectResponse(url=presigned_url, status_code=307)


# Kept explicit, and passed explicitly below, rather than relying on
# generate_presigned_url's default: expires_in is a promise to the caller, and if
# the service default were changed this response would quietly start lying about
# when the URL stops working.
DOWNLOAD_URL_TTL_SECONDS = 3600


@router.get(
    "/download-url",
    response_model=PresignedDownload,
    summary="Get a presigned URL for a file",
    dependencies=[Depends(require_file_download)],
)
def get_download_url(
    response: Response,
    path: str = Query(
        ...,
        description="S3 URI of the file (e.g., s3://bucket/path/file.txt)"
    ),
    s3_client=Depends(get_s3_client),
) -> PresignedDownload:
    """
    Return a time-limited URL for downloading a file directly from S3.

    The authenticated counterpart to GET /files/download. A browser cannot put a
    token on a link it navigates to, so the UI calls this with its token, reads
    the URL from the response, and then navigates to S3 -- which is what the old
    endpoint's redirect did anyway, minus the ability to check anything first.

    Guarded on the global plane rather than per project, because the parameter is
    an arbitrary S3 URI and nothing maps a URI back to a project. That is the
    same reason file:browse is global-only; it is a known limitation recorded in
    docs/RBAC.md, not an oversight. `member` holds file:download, so every
    authenticated caller can use this today.
    """
    # A presigned URL is a bearer credential for the object. Caching it in a
    # shared proxy would hand it to whoever asks next.
    response.headers["Cache-Control"] = "no-store"

    url = services.generate_presigned_url(
        s3_path=path, s3_client=s3_client,
        expiration=DOWNLOAD_URL_TTL_SECONDS,
    )
    return PresignedDownload(url=url, expires_in=DOWNLOAD_URL_TTL_SECONDS)


@router.patch(
    "/{file_id}",
    response_model=FilePublic,
    summary="Update a file record (superuser only)",
    dependencies=[Depends(require_permission(Permission.FILE_UPDATE))],
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
    dependencies=[Depends(require_permission(Permission.FILE_DELETE))],
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
    dependencies=[Depends(require_permission(Permission.FILE_READ))],
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
