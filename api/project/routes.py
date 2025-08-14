"""
Routes/endpoints for the Project API
"""
from typing import Literal
from fastapi import APIRouter, Query, status
from core.deps import (
  SessionDep,
  OpenSearchDep
)
from api.project.models import (
  Project,
  ProjectCreate,
  ProjectPublic,
  ProjectsPublic
)
from api.samples.models import (
  SampleCreate,
  SamplePublic,
  SamplesPublic
)
import api.project.services as services
import api.samples.services as sample_services

router = APIRouter(prefix="/projects", tags=["Project Endpoints"])

###############################################################################
# Projects Endpoints /api/v1/projects/
###############################################################################

@router.post(
  "",
  response_model=ProjectPublic,
  tags=["Project Endpoints"],
  status_code=status.HTTP_201_CREATED
)
def create_project(
  session: SessionDep,
  opensearch_client: OpenSearchDep,
  project_in: ProjectCreate
) -> Project:
  """
  Create a new project with optional attributes.
  """
  return services.create_project(
    session=session,
    project_in=project_in,
    opensearch_client=opensearch_client
  )

@router.get(
  "",
  response_model=ProjectsPublic,
  tags=["Project Endpoints"]
)
def get_projects(
  session: SessionDep, 
  page: int = Query(1, description="Page number (1-indexed)"), 
  per_page: int = Query(20, description="Number of items per page"),
  sort_by: str = Query('project_id', description="Field to sort by"),
  sort_order: Literal['asc', 'desc'] = Query('asc', description="Sort order (asc or desc)")
) -> ProjectsPublic:
  """
  Returns a paginated list of projects.
  """
  return services.get_projects(
    session=session, 
    page=page,
    per_page=per_page,
    sort_by=sort_by,
    sort_order=sort_order
  )

###############################################################################
# Project Endpoints /api/v1/projects/{project_id}
###############################################################################

@router.get(
  "/{project_id}",
  response_model=ProjectPublic,
  tags=["Project Endpoints"]
)
def get_project_by_project_id(session: SessionDep, project_id: str) -> Project:
  """
  Returns a single project by its project_id.
  Note: This is different from its internal "id".
  """
  return services.get_project_by_project_id(
    session=session,
    project_id=project_id
  )

###############################################################################
# Samples Endpoints /api/v1/projects/{project_id}/samples
###############################################################################

@router.get(
  "/{project_id}/samples",
  response_model=SamplesPublic,
  tags=["Sample Endpoints"] # TODO: This causes the docs to misbehave :(
)
def get_samples(
  session: SessionDep,
  project_id: str,
  page: int = Query(1, description="Page number (1-indexed)"),
  per_page: int = Query(20, description="Number of items per page"),
  sort_by: str = Query('sample_id', description="Field to sort by"),
  sort_order: Literal['asc', 'desc'] = Query('asc', description="Sort order (asc or desc)")
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
    sort_order=sort_order
  )

@router.post(
  "/{project_id}/samples",
  response_model=SamplePublic,
  tags=["Sample Endpoints"],
  status_code=status.HTTP_201_CREATED
)
def add_sample_to_project(session: SessionDep, opensearch_client: OpenSearchDep, project_id: str, sample_in: SampleCreate) -> SamplePublic:
  """
  Create a new sample with optional attributes.
  """
  return sample_services.add_sample_to_project(session=session, opensearch_client=opensearch_client, project_id=project_id, sample_in=sample_in)