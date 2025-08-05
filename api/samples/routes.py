"""
Routes/endpoints for the Samples API
"""
from typing import Literal
from fastapi import APIRouter, Query, status
from core.deps import (
  SessionDep
)
from api.samples.models import (
  Sample,
  SampleCreate,
  SamplePublic,
  SamplesPublic
)
import api.samples.services as services

router = APIRouter(prefix="/samples", tags=["Sample Endpoints"])

@router.post(
  "",
  response_model=SamplePublic,
  tags=["Sample Endpoints"],
  status_code=status.HTTP_201_CREATED
)
def create_sample(session: SessionDep, sample_in: SampleCreate) -> Sample:
  """
  Create a new sample with optional attributes.
  """
  return services.create_sample(session=session, sample_in=sample_in)

@router.get(
  "",
  response_model=SamplesPublic,
  tags=["Sample Endpoints"]
)
def get_samples(
  session: SessionDep, 
  page: int = Query(1, description="Page number (1-indexed)"), 
  per_page: int = Query(20, description="Number of items per page"),
  sort_by: str = Query('sample_id', description="Field to sort by"),
  sort_order: Literal['asc', 'desc'] = Query('asc', description="Sort order (asc or desc)")
) -> SamplesPublic:
  """
  Returns a paginated list of samples.
  """
  return services.get_samples(
    session=session, 
    page=page,
    per_page=per_page,
    sort_by=sort_by,
    sort_order=sort_order
  )

@router.get(
  "/{sample_id}",
  response_model=SamplePublic,
  tags=["Sample Endpoints"]
)
def get_sample_by_sample_id(session: SessionDep, sample_id: str) -> Sample:
  """
  Returns a single sample by its sample_id.
  Note: This is different from its internal "id".
  """
  return services.get_sample_by_sample_id(
    session=session,
    sample_id=sample_id
  )