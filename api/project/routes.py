"""
Routes/endpoints for the Project API
"""

from typing import Literal
from fastapi import APIRouter, Query, status, UploadFile, File
from fastapi.responses import StreamingResponse
from core.deps import SessionDep, OpenSearchDep
from api.project.models import Project, ProjectCreate, ProjectPublic, ProjectsPublic
from api.samples.models import SampleCreate, SamplePublic, SamplesPublic
from api.project import services
from api.samples import services as sample_services

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
) -> Project:
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


###############################################################################
# Project Endpoints /api/v1/projects/{project_id}
###############################################################################


@router.get("/{project_id}", response_model=ProjectPublic, tags=["Project Endpoints"])
def get_project_by_project_id(session: SessionDep, project_id: str) -> ProjectPublic:
    """
    Returns a single project by its project_id.
    Note: This is different from its internal "id".
    """
    return services.get_project_by_project_id(session=session, project_id=project_id)


###############################################################################
# Samples Endpoints /api/v1/projects/{project_id}/samples
###############################################################################


@router.post(
    "/{project_id}/samples",
    response_model=SamplePublic,
    tags=["Sample Endpoints"],
    status_code=status.HTTP_201_CREATED,
)
def add_sample_to_project(
    session: SessionDep,
    opensearch_client: OpenSearchDep,
    project_id: str,
    sample_in: SampleCreate,
) -> SamplePublic:
    """
    Create a new sample with optional attributes.
    """
    return sample_services.add_sample_to_project(
        session=session,
        opensearch_client=opensearch_client,
        project_id=project_id,
        sample_in=sample_in,
    )


@router.get(
    "/{project_id}/samples", response_model=SamplesPublic, tags=["Sample Endpoints"]
)
def get_samples(
    session: SessionDep,
    project_id: str,
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
    return sample_services.get_samples(
        session=session,
        project_id=project_id,
        page=page,
        per_page=per_page,
        sort_by=sort_by,
        sort_order=sort_order,
    )


@router.get(
    "/{project_id}/samples/download",
    response_class=StreamingResponse,
    response_model=None,
    status_code=status.HTTP_200_OK,
    tags=["Sample Endpoints"],
)
def download_samples(
    session: SessionDep,
    project_id: str,
) -> StreamingResponse:
    """
    Download all samples as a TSV for a given project.
    """
    return sample_services.download_samples_as_tsv(
        session=session,
        project_id=project_id,
    )


@router.post(
    "/{project_id}/samples/upload",
    response_model=SamplesPublic,
    tags=["Sample Endpoints"],
    status_code=status.HTTP_201_CREATED,
)
async def upload_samples_to_project(
    session: SessionDep,
    opensearch_client: OpenSearchDep,
    project_id: str,
    file: UploadFile = File(...),
) -> SamplesPublic:
    """
    Upload samples from a TSV file to a specific project.
    """
    # Read file content
    content = await file.read()
    tsv_content = content.decode("utf-8")

    return sample_services.upload_samples_from_tsv(
        session=session,
        opensearch_client=opensearch_client,
        project_id=project_id,
        tsv_content=tsv_content,
    )
