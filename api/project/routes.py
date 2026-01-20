"""
Routes/endpoints for the Project API
"""

from typing import Literal
from fastapi import APIRouter, Query, status, Depends
from core.deps import SessionDep, OpenSearchDep, get_s3_client
from api.project.models import (
    ProjectCreate,
    ProjectPublic,
    ProjectsPublic,
    PipelineConfig,
    PipelineConfigsResponse,
    ProjectOption,
)
from api.samples.models import SampleCreate, SamplePublic, SamplesPublic, Attribute
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
# Project Endpoints /api/v1/projects/workflows
###############################################################################


@router.get("/workflows", response_model=list[str], tags=["Project Endpoints"])
def list_workflow_configs(
    session: SessionDep,
    s3_client=Depends(get_s3_client),
) -> list[str]:
    """
    List all available project workflow configs from S3.

    Returns a list of workflow IDs (config filenames without extensions).
    """
    return services.list_workflow_configs(session=session, s3_client=s3_client)


@router.get(
    "/workflows/configs",
    response_model=PipelineConfigsResponse,
    tags=["Project Endpoints"],
)
def get_all_workflow_configs(
    session: SessionDep,
    s3_client=Depends(get_s3_client),
) -> PipelineConfigsResponse:
    """
    Retrieve and parse all project workflow configurations from S3.

    Returns:
        PipelineConfigsResponse containing all parsed workflow configurations
    """
    return services.get_all_workflow_configs(session=session, s3_client=s3_client)


@router.get(
    "/workflows/{workflow_id}",
    response_model=PipelineConfig,
    tags=["Project Endpoints"],
)
def get_workflow_config(
    workflow_id: str,
    session: SessionDep,
    s3_client=Depends(get_s3_client),
) -> PipelineConfig:
    """
    Retrieve a specific workflow configuration.

    Args:
        workflow_id: The workflow identifier (filename without extension)

    Returns:
        Complete workflow configuration
    """
    return services.get_workflow_config(
        session=session, workflow_id=workflow_id, s3_client=s3_client
    )


@router.get(
    "/actions",
    response_model=list[ProjectOption],
    tags=["Project Endpoints"],
)
def get_project_actions() -> list[ProjectOption]:
    """
    Get available project actions.

    Returns:
        List of available project actions with labels, values, and descriptions
    """
    return [
        ProjectOption(
            label="Create Project",
            value="create-project",
            description="Create a new project in one of the supported platforms",
        ),
        ProjectOption(
            label="Export Project Results",
            value="export-project-results",
            description="Export the project results from one of the supported platforms",
        ),
    ]


@router.get(
    "/platforms",
    response_model=list[ProjectOption],
    tags=["Project Endpoints"],
)
def get_project_platforms() -> list[ProjectOption]:
    """
    Get available project platforms.

    Returns:
        List of available platforms with labels, values, and descriptions
    """
    return [
        ProjectOption(
            label="Arvados",
            value="arvados",
            description="Arvados platform",
        ),
        ProjectOption(
            label="SevenBridges",
            value="sevenbridges",
            description="SevenBridges platform",
        ),
    ]


@router.get(
    "/types",
    response_model=list[dict],
    tags=["Project Endpoints"],
)
def get_project_types(
    session: SessionDep,
    action: Literal["create-project", "export-project-results"] = Query(
        description="Project action"
    ),
    platform: Literal["arvados", "sevenbridges"] = Query(
        description="Project platform"
    ),
    s3_client=Depends(get_s3_client),
) -> list[dict]:
    """
    Get available project types based on action and platform.

    Args:
        action: The project action
        platform: The platform
        
    Returns:
        List of project types with label, value, and project_type
    """
    return services.get_project_types_for_action_and_platform(
        session=session,
        action=action,
        platform=platform,
        s3_client=s3_client
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


@router.put(
    "/{project_id}/samples/{sample_id}",
    response_model=SamplePublic,
    tags=["Sample Endpoints"],
)
def update_sample_in_project(
    session: SessionDep,
    project_id: str,
    sample_id: str,
    attribute: Attribute,
) -> SamplePublic:
    """
    Update an existing sample in a project.
    """
    return sample_services.update_sample_in_project(
        session=session,
        project_id=project_id,
        sample_id=sample_id,
        attribute=attribute,
    )
