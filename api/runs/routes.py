"""
Routes/endpoints for the Runs API

HTTP   URI                             Action
----   ---                             ------
GET    /api/v1/runs                    Retrieve a list of sequencing runs
POST   /api/v1/runs                    Create/Add a sequencing run
GET    /api/v1/runs/search             Search sequencing runs
GET    /api/v1/runs/[id]               Retrieve info about a specific run
PUT    /api/v1/runs/[id]               Update a Run State
GET    /api/v1/runs/[id]/sample_sheet  Retrieve the sample sheet for the run
POST   /api/v1/runs/[id]/samples       Post new samples after demux
POST   /api/v1/runs/[id]/demultiplex   Demultiplex a run
GET    /api/v1/runs/[id]/metrics       Retrieve demux metrics from Stat.json
"""

from typing import Literal
from fastapi import APIRouter, Query, status, UploadFile, File
from core.deps import SessionDep, OpenSearchDep
from api.runs.models import (
    IlluminaMetricsResponseModel,
    SequencingRun,
    SequencingRunCreate,
    SequencingRunPublic,
    SequencingRunsPublic,
    SequencingRunUpdateRequest,
    IlluminaSampleSheetResponseModel,
    DemultiplexAnalysisAvailable
)
from api.runs import services

router = APIRouter(prefix="/runs", tags=["Run Endpoints"])

###############################################################################
# Runs Endpoints /api/v1/runs/
###############################################################################


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

###############################################################################
# Runs Endpoints /api/v1/runs/search
###############################################################################


@router.get(
    "/search",
    response_model=SequencingRunsPublic,
    status_code=status.HTTP_200_OK,
    tags=["Run Endpoints"],
)
def search_runs(
    session: SessionDep,
    opensearch_client: OpenSearchDep,
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
        client=opensearch_client,
        query=query,
        page=page,
        per_page=per_page,
        sort_by=sort_by,
        sort_order=sort_order,
    )


@router.post(
    "/search",
    status_code=status.HTTP_201_CREATED,
    tags=["Run Endpoints"],
)
def reindex_runs(
    session: SessionDep,
    client: OpenSearchDep,
):
    """
    Reindex runs in database with OpenSearch
    """
    services.reindex_runs(session, client)
    return 'OK'

###############################################################################
# Runs Endpoints /api/v1/runs/demultiplex
###############################################################################


@router.get(
    "/demultiplex",
    response_model=DemultiplexAnalysisAvailable,
    status_code=status.HTTP_200_OK,
    tags=["Run Endpoints"],
)
def get_multiplex_workflows(session: SessionDep) -> DemultiplexAnalysisAvailable:
    """
    Placeholder endpoint for getting available demultiplex workflows.
    """
    # TBD: How do we want to manage available demultiplexing workflows?
    # This should be a list of available demultiplexing workflows in a database table
    # and is dependent on how we support GA4GH WES API.

    # return services.get_demultiplex_workflows(session=session)
    return DemultiplexAnalysisAvailable(demux_analysis_name=["bcl2fastq", "cellranger"])


@router.post(
    "/demultiplex",
    response_model=SequencingRunPublic,
    status_code=status.HTTP_202_ACCEPTED,
    tags=["Run Endpoints"],
)
def demultiplex_run(session: SessionDep, run_barcode: str) -> SequencingRunPublic:
    """
    Submit a demultiplex job for a specific run.
    """
    # return services.demultiplex_run(session=session, run_barcode=run_barcode)
    return services.get_run(session=session, run_barcode=run_barcode)


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


@router.post(
    "/{run_barcode}/samplesheet",
    response_model=IlluminaSampleSheetResponseModel,
    status_code=status.HTTP_201_CREATED,
    tags=["Run Endpoints"],)
def post_run_samplesheet(
    session: SessionDep,
    run_barcode: str,
    file: UploadFile = File(..., description="File to upload"),
) -> IlluminaSampleSheetResponseModel:
    """
    Upload a samplesheet to a run.
    """
    return services.upload_samplesheet(
        session=session,
        run_barcode=run_barcode,
        file=file,
    )


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
