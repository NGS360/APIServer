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

from typing import Literal
from fastapi import APIRouter, Query, status, HTTPException
from core.deps import SessionDep, OpenSearchDep
from api.runs.models import (
    IlluminaMetricsResponseModel,
    SequencingRun,
    SequencingRunCreate,
    SequencingRunPublic,
    SequencingRunsPublic,
    SequencingRunUpdateRequest,
    IlluminaSampleSheetResponseModel,
)
from api.runs import services

router = APIRouter(prefix="/runs", tags=["Run Endpoints"])


@router.post(
    "",
    response_model=SequencingRunPublic,
    tags=["Run Endpoints"],
    status_code=status.HTTP_201_CREATED,
)
def add_run(
    session: SessionDep,
    opensearch_client: OpenSearchDep,
    sequencingrun_in: SequencingRunCreate,
) -> SequencingRun:
    """
    Create a new project with optional attributes.
    """
    run = services.add_run(
        session=session,
        sequencingrun_in=sequencingrun_in,
        opensearch_client=opensearch_client,
    )
    return SequencingRunPublic(
        run_date=run.run_date,
        machine_id=run.machine_id,
        run_number=run.run_number,
        flowcell_id=run.flowcell_id,
        experiment_name=run.experiment_name,
        run_folder_uri=run.run_folder_uri,
        status=run.status,
        run_time=run.run_time,
        barcode=run.barcode,
    )


@router.get(
    "",
    response_model=SequencingRunsPublic,
    status_code=status.HTTP_200_OK,
    tags=["Run Endpoints"],
)
def get_runs(
    session: SessionDep,
    page: int = Query(1, description="Page number (1-indexed)"),
    per_page: int = Query(20, description="Number of items per page"),
    sort_by: str = Query("barcode", description="Field to sort by"),
    sort_order: Literal["asc", "desc"] = Query(
        "asc", description="Sort order (asc or desc)"
    ),
) -> SequencingRunsPublic:
    """
    Retrieve a list of all sequencing runs.
    """
    return services.get_runs(
        session=session,
        page=page,
        per_page=per_page,
        sort_by=sort_by,
        sort_order=sort_order,
    )


@router.get(
    "/search",
    response_model=SequencingRunsPublic,
    status_code=status.HTTP_200_OK,
    tags=["Run Endpoints"],
)
def search_runs(
    session: SessionDep,
    client: OpenSearchDep,
    query: str = Query(description="Search query string"),
    page: int = Query(1, description="Page number (1-indexed)"),
    per_page: int = Query(20, description="Number of items per page"),
    sort_by: Literal["barcode", "experiment_name"] | None = Query(
        "barcode", description="Field to sort by"
    ),
    sort_order: Literal["asc", "desc"] | None = Query(
        "asc", description="Sort order (asc or desc)"
    ),
) -> SequencingRunsPublic:
    '''
    Search for sequencing runs using OpenSearch.
    '''
    return services.search_runs(
        session=session,
        client=client,
        query=query,
        page=page,
        per_page=per_page,
        sort_by=sort_by,
        sort_order=sort_order,
    )


@router.get(
    "/{run_barcode}",
    response_model=SequencingRunPublic,
    status_code=status.HTTP_200_OK,
    tags=["Run Endpoints"],
)
def get_run(session: SessionDep, run_barcode: str) -> SequencingRunPublic:
    """
    Retrieve a sequencing run.
    """
    return services.get_run(session=session, run_barcode=run_barcode)


@router.put(
    "/{run_barcode}",
    response_model=SequencingRunPublic,
    tags=["Run Endpoints"],
)
def update_run(
    session: SessionDep,
    run_barcode: str,
    update_request: SequencingRunUpdateRequest,
) -> SequencingRunPublic:
    """
    Update the status of a specific run.
    Valid status values are: "In Progress", "Uploading", "Ready", "Resync"
    """
    return services.update_run(
        session=session,
        run_barcode=run_barcode,
        run_status=update_request.run_status
    )


@router.get(
    "/{run_barcode}/samplesheet",
    response_model=IlluminaSampleSheetResponseModel,
    status_code=status.HTTP_200_OK,
    tags=["Run Endpoints"],
)
def get_run_samplesheet(session: SessionDep, run_barcode: str) -> IlluminaSampleSheetResponseModel:
    """
    Retrieve the sample sheet for a specific run.
    """
    return services.get_run_samplesheet(session=session, run_barcode=run_barcode)


@router.get(
    "/{run_barcode}/metrics",
    response_model=IlluminaMetricsResponseModel,
    status_code=status.HTTP_200_OK,
    tags=["Run Endpoints"],
)
def get_run_metrics(session: SessionDep, run_barcode: str) -> IlluminaMetricsResponseModel:
    """
    Retrieve demultiplexing metrics for a specific run.
    """
    return services.get_run_metrics(session=session, run_barcode=run_barcode)
