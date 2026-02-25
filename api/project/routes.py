"""
Routes/endpoints for the Project API
"""

from typing import Literal
from fastapi import APIRouter, Query, status, Depends
from core.deps import SessionDep, OpenSearchDep, get_s3_client
from api.auth.deps import CurrentUser
from api.jobs.models import BatchJobPublic
from api.project.deps import ProjectDep
from api.project.models import (
    ProjectCreate,
    ProjectUpdate,
    ProjectPublic,
    ProjectsPublic,
)
from api.samples.models import SampleCreate, SamplePublic, SamplesPublic, Attribute
from api.project import services
from api.actions.models import ActionSubmitRequest

router = APIRouter(prefix="/projects")

###############################################################################
# Projects Endpoints /api/v1/projects/
###############################################################################


@router.post(
    "",
    response_model=ProjectPublic,
    tags=["Project Endpoints"],
    status_code=status.HTTP_201_CREATED,
)
def create_project(
    session: SessionDep, opensearch_client: OpenSearchDep, project_in: ProjectCreate
) -> ProjectPublic:
    """
    Create a new project with optional attributes.
    """
    return services.create_project(
        session=session, project_in=project_in, opensearch_client=opensearch_client
    )


@router.get(
    "",
    response_model=ProjectsPublic,
    status_code=status.HTTP_200_OK,
    tags=["Project Endpoints"],
)
def get_projects(
    session: SessionDep,
    page: int = Query(1, description="Page number (1-indexed)"),
    per_page: int = Query(20, description="Number of items per page"),
    sort_by: str = Query("project_id", description="Field to sort by"),
    sort_order: Literal["asc", "desc"] = Query(
        "asc", description="Sort order (asc or desc)"
    ),
) -> ProjectsPublic:
    """
    Returns a paginated list of projects.
    """
    return services.get_projects(
        session=session,
        page=page,
        per_page=per_page,
        sort_by=sort_by,
        sort_order=sort_order,
    )

###############################################################################
# Projects Endpoints /api/v1/projects/search
###############################################################################


@router.get(
    "/search",
    response_model=ProjectsPublic,
    status_code=status.HTTP_200_OK,
    tags=["Project Endpoints"],
)
def search_projects(
    session: SessionDep,
    client: OpenSearchDep,
    query: str = Query(description="Search query string"),
    page: int = Query(1, description="Page number (1-indexed)"),
    per_page: int = Query(20, description="Number of items per page"),
    sort_by: Literal["project_id", "name"] | None = Query(
        "name", description="Field to sort by"
    ),
    sort_order: Literal["asc", "desc"] | None = Query(
        "asc", description="Sort order (asc or desc)"
    ),
) -> ProjectsPublic:
    """
    Search projects by project_id or name.
    """
    return services.search_projects(
        session=session,
        client=client,
        query=query,
        page=page,
        per_page=per_page,
        sort_by=sort_by,
        sort_order=sort_order,
    )


@router.post(
    "/search",
    status_code=status.HTTP_201_CREATED,
    tags=["Project Endpoints"],
)
def reindex_projects(
    session: SessionDep,
    client: OpenSearchDep,
):
    """
    Reindex projects in database with OpenSearch
    """
    services.reindex_projects(session, client)
    return 'OK'

###############################################################################
# Project Endpoints /api/v1/projects/{project_id}
###############################################################################


@router.get("/{project_id}", response_model=ProjectPublic, tags=["Project Endpoints"])
def get_project_by_project_id(session: SessionDep, project: ProjectDep) -> ProjectPublic:
    """
    Returns a single project by its project_id.
    Note: This is different from its internal "id".
    """
    return services.get_project_by_project_id(session=session, project_id=project.project_id)


@router.put(
    "/{project_id}",
    response_model=ProjectPublic,
    status_code=status.HTTP_200_OK,
    tags=["Project Endpoints"],
)
def update_project(
    session: SessionDep,
    opensearch_client: OpenSearchDep,
    project: ProjectDep,
    update_request: ProjectUpdate,
) -> ProjectPublic:
    """
    Update information about a specific project.
    """
    return services.update_project(
        session=session,
        opensearch_client=opensearch_client,
        project_id=project.project_id,
        update_request=update_request,
    )

###############################################################################
# "Samples" Endpoints /api/v1/projects/{project_id}/samples
###############################################################################


@router.post(
    "/{project_id}/samples",
    response_model=SamplePublic,
    tags=["Project Endpoints"],
    status_code=status.HTTP_201_CREATED,
)
def add_sample_to_project(
    session: SessionDep,
    opensearch_client: OpenSearchDep,
    project: ProjectDep,
    sample_in: SampleCreate,
) -> SamplePublic:
    """
    Create a new sample with optional attributes.
    """
    return services.add_sample_to_project(
        session=session,
        opensearch_client=opensearch_client,
        project=project,
        sample_in=sample_in,
    )


@router.get(
    "/{project_id}/samples", response_model=SamplesPublic, tags=["Project Endpoints"]
)
def get_project_samples(
    session: SessionDep,
    project: ProjectDep,
    page: int = Query(1, description="Page number (1-indexed)"),
    per_page: int = Query(20, description="Number of items per page"),
    sort_by: str = Query("sample_id", description="Field to sort by"),
    sort_order: Literal["asc", "desc"] = Query(
        "asc", description="Sort order (asc or desc)"
    ),
) -> SamplesPublic:
    """
    Returns a paginated list of samples.
    """
    return services.get_project_samples(
        session=session,
        project=project,
        page=page,
        per_page=per_page,
        sort_by=sort_by,
        sort_order=sort_order,
    )


@router.put(
    "/{project_id}/samples/{sample_id}",
    response_model=SamplePublic,
    tags=["Project Endpoints"],
)
def update_sample_in_project(
    session: SessionDep,
    project: ProjectDep,
    sample_id: str,
    attribute: Attribute,
) -> SamplePublic:
    """
    Update an existing sample in a project.
    """
    return services.update_sample_in_project(
        session=session,
        project=project,
        sample_id=sample_id,
        attribute=attribute,
    )


###############################################################################
# Action Submission Endpoint /api/v1/projects/{project_id}/actions/submit
###############################################################################


@router.post(
    "/{project_id}/actions/submit",
    # response_model=BatchJobPublic,  # COMMENTED OUT FOR TESTING
    tags=["Project Endpoints"],
    status_code=status.HTTP_201_CREATED,
)
def submit_pipeline_job(
    project: ProjectDep,
    request: ActionSubmitRequest,
    current_user: CurrentUser,
    session: SessionDep,
    s3_client=Depends(get_s3_client),
) -> BatchJobPublic:
    """
    Submit a pipeline job to AWS Batch for a project.

    This endpoint validates the project exists, retrieves the appropriate pipeline
    configuration based on the project type, determines the command to execute
    based on the action (create-project or export-project-results), interpolates
    template variables, and submits the job to AWS Batch.

    Args:
        session: Database session
        project_id: The project ID
        request: Pipeline submission request containing:
            - action: Pipeline action (create-project or export-project-results)
            - platform: Platform name (Arvados or SevenBridges)
            - project_type: Pipeline workflow type (e.g., RNA-Seq, WGS)
            - reference: Export reference (required for export-project-results)
            - auto_release: Auto-release flag for export action (default: False)
        current_user: Currently authenticated user
        s3_client: S3 client for retrieving pipeline configs

    Returns:
        BatchJobPublic: The created batch job information
    """
    batch_job = services.submit_pipeline_job(
        session=session,
        project=project,
        action=request.action,
        platform=request.platform,
        project_type=request.project_type,
        username=current_user.username,
        reference=request.reference,
        auto_release=request.auto_release,
        s3_client=s3_client
    )

    return BatchJobPublic.model_validate(batch_job)


###############################################################################
# Action Submission Endpoint /api/v1/projects/{project_id}/ingest
###############################################################################

@router.post(
    "/{project_id}/ingest",
    tags=["Project Endpoints"],
    status_code=status.HTTP_201_CREATED,
)
def ingest_vendor_data(
    session: SessionDep,
    project: ProjectDep,
    user: CurrentUser,
    files_uri: str = Query(
        ..., description="Source Bucket/Prefix of the data to be ingested"
    ),
    manifest_uri: str = Query(
        ..., description="URI (S3) path to the vendor manifest"
    )
) -> BatchJobPublic:
    """
    Ingest vendor data for a project.

    Returns:
        BatchJobPublic: The created batch job information
    """
    batch_job = services.ingest_vendor_data(
        session, project, user.username, files_uri, manifest_uri)
    return BatchJobPublic.model_validate(batch_job)
