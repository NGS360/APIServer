"""
Routes/endpoints for the Samples API
"""
from typing import Literal
from fastapi import APIRouter, Query, status
from core.deps import (
  SessionDep,
  OpenSearchDep
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
def create_sample(session: SessionDep, opensearch_client: OpenSearchDep, sample_in: SampleCreate) -> SamplePublic:
  """
  Create a new sample with optional attributes.
  """
  return services.create_sample(session=session, sample_in=sample_in)

#@router.get(
#  "/{sample_id}",
#  response_model=SamplePublic,
#  tags=["Sample Endpoints"]
#)
#def get_sample_by_sample_id(session: SessionDep, sample_id: str) -> Sample:
#  """
#  Returns a single sample by its sample_id.
#  Note: This is different from its internal "id".
#  """
#  return services.get_sample_by_sample_id(
#    session=session,
#    sample_id=sample_id
#  )