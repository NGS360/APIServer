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