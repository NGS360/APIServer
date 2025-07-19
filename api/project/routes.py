"""
Routes/endpoints for the Project API
"""
from typing import Literal
from fastapi import APIRouter, Query
from core.deps import (
  SessionDep
)
from api.project.models import (
  Project,
  ProjectCreate,
  ProjectPublic,
  ProjectsPublic
)
import api.project.services as services

router = APIRouter()

@router.post(
  "/create_project",
  response_model=ProjectPublic,
  tags=["Project Endpoints"]
)
def create_project(session: SessionDep, project_in: ProjectCreate) -> Project:
  """
  Create a new project with optional attributes.
  """
  return services.create_project(session=session, project_in=project_in)

@router.get(
  "/read_projects",
  response_model=ProjectsPublic,
  tags=["Project Endpoints"]
)
def read_projects(
  session: SessionDep, 
  page: int = Query(1, description="Page number (1-indexed)"), 
  per_page: int = Query(20, description="Number of items per page"),
  sort_by: str = Query('project_id', description="Field to sort by"),
  sort_order: Literal['asc', 'desc'] = Query('asc', description="Sort order (asc or desc)")
) -> ProjectsPublic:
  """
  Returns a paginated list of projects.
  """
  return services.read_projects(
    session=session, 
    page=page,
    per_page=per_page,
    sort_by=sort_by,
    sort_order=sort_order
  )

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