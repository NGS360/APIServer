"""
Routes/endpoints for the Runs API

HTTP   URI                             Action
----   ---                             ------
GET    /api/v0/runs                    Retrieve a list of sequencing runs
POST   /api/v0/runs                    Create/Add a sequencing run
GET    /api/v0/runs/[id]               Retrieve info about a specific run
PUT    /api/v0/runs/[id]               Update a Run State
GET    /api/v0/runs/[id]/sample_sheet  Retrieve the sample sheet for the run
POST   /api/v0/runs/[id]/samples       Post new samples after demux
POST   /api/v0/runs/[id]/demultiplex   Demultiplex a run
GET    /api/v0/runs/[id]/metrics       Retrieve demux metrics from Stat.json
"""
from fastapi import APIRouter, Query, status
from typing import Literal
from core.deps import SessionDep
from api.runs.models import (
    SequencingRunsPublic
)
import api.runs.services as services

router = APIRouter(prefix="/runs", tags=["Run Endpoints"])

@router.get(
    "",
    response_model=SequencingRunsPublic,
    status_code=status.HTTP_200_OK,
    tags=["Run Endpoints"]
)
def get_runs(
  session: SessionDep, 
  page: int = Query(1, description="Page number (1-indexed)"), 
  per_page: int = Query(20, description="Number of items per page"),
  sort_by: str = Query('project_id', description="Field to sort by"),
  sort_order: Literal['asc', 'desc'] = Query('asc', description="Sort order (asc or desc)")
) -> SequencingRunsPublic:
    """
    Retrieve a list of all sequencing runs.
    """
    return services.get_runs(
        session=session, 
        page=page,
        per_page=per_page,
        sort_by=sort_by,
        sort_order=sort_order
    )
