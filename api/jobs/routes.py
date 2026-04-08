"""
Routes/endpoints for the Jobs API

HTTP   URI                  Action
----   ---                  ------
GET    /api/v1/jobs         Retrieve a list of batch jobs
POST   /api/v1/jobs         Submit a new batch job to AWS Batch
GET    /api/v1/jobs/[id]    Retrieve info about a specific job
PUT    /api/v1/jobs/[id]    Update a batch job
"""

from typing import Optional, Literal
from fastapi import APIRouter, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from core.deps import SessionDep
from api.jobs.models import (
    BatchJobSubmit,
    BatchJobUpdate,
    BatchJobPublic,
    BatchJobsPublic,
    JobStatus
)
from api.jobs import services

router = APIRouter(prefix="/jobs", tags=["Job Endpoints"])


###############################################################################
# Jobs Endpoints /api/v1/jobs/
###############################################################################


@router.post(
    "",
    response_model=BatchJobPublic,
    tags=["Job Endpoints"],
    status_code=status.HTTP_201_CREATED,
)
def submit_job(
    session: SessionDep,
    job_in: BatchJobSubmit,
) -> BatchJobPublic:
    """
    Submit a new batch job to AWS Batch and create a database record.

    This endpoint submits a job directly to AWS Batch and creates a tracking
    record in the database. The job will be queued in AWS Batch and its status
    can be monitored using the GET endpoints.

    Args:
        session: Database session
        job_in: Job submission data including AWS Batch parameters

    Returns:
        Created job information with AWS job ID
    """
    container_overrides = {
        "command": job_in.command.split(),
        "environment": [
            {"name": env.name, "value": env.value}
            for env in (job_in.environment or [])
        ]
    }

    job = services.submit_batch_job(
        session=session,
        job_name=job_in.job_name,
        container_overrides=container_overrides,
        job_def=job_in.job_definition,
        job_queue=job_in.job_queue,
        user=job_in.user,
    )
    return BatchJobPublic.model_validate(job)


@router.get(
    "",
    response_model=BatchJobsPublic,
    tags=["Job Endpoints"],
)
def get_jobs(
    session: SessionDep,
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    user: Optional[str] = Query(None, description="Filter by user"),
    status_filter: Optional[JobStatus] = Query(None, description="Filter by status"),
    sort_by: str = Query("submitted_on", description="Field to sort by"),
    sort_order: Literal["asc", "desc"] = Query("desc", description="Sort order (asc or desc)"),
) -> BatchJobsPublic:
    """
    Retrieve a list of batch jobs with optional filtering and sorting.

    Args:
        session: Database session
        skip: Number of records to skip
        limit: Maximum number of records to return
        user: Optional user filter
        status_filter: Optional status filter
        sort_by: Field to sort by (defaults to 'submitted_on')
        sort_order: Sort order 'asc' or 'desc' (defaults to 'desc')

    Returns:
        List of jobs and total count
    """
    jobs, total_count = services.get_batch_jobs(
        session=session,
        skip=skip,
        limit=limit,
        user=user,
        status_filter=status_filter,
        sort_by=sort_by,
        sort_order=sort_order,
    )
    return BatchJobsPublic(
        data=[BatchJobPublic.model_validate(job) for job in jobs],
        count=total_count
    )


###############################################################################
# Job Endpoints /api/v1/jobs/{job_id}
###############################################################################

@router.get(
    "/{job_id}",
    response_model=BatchJobPublic,
    tags=["Job Endpoints"],
    responses={
        404: {"description": "Job not found"}
    }
)
def get_job(
    session: SessionDep,
    job_id: str,
) -> BatchJobPublic:
    """
    Retrieve information about a specific batch job.

    Args:
        session: Database session
        job_id: string representation of the job UUID

    Returns:
        Job information
    """
    job = services.get_batch_job(session, job_id)
    if not job:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No job found with id {job_id}"
        )
    return BatchJobPublic.model_validate(job)


@router.put(
    "/{job_id}",
    response_model=BatchJobPublic,
    tags=["Job Endpoints"],
    responses={
        404: {"description": "Job not found"}
    }
)
def update_job(
    session: SessionDep,
    job_id: str,
    job_update: BatchJobUpdate,
) -> BatchJobPublic:
    """
    Find and Update a batch job.

    Args:
        session: Database session
        job_id: Job UUID
        job_update: Job update data

    Returns:
        Updated job information
    """
    # Make sure there is an id to find the job
    job = services.get_batch_job(session, job_id)
    if not job:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No job found with id {job_id}"
        )
    updated_job = services.update_batch_job(session, job, job_update)
    return BatchJobPublic.model_validate(updated_job)


###############################################################################
# Job Endpoints /api/v1/jobs/{job_id}/log
###############################################################################


@router.get(
    "/{job_id}/log",
    response_class=StreamingResponse,
    tags=["Job Endpoints"],
    responses={
        404: {"description": "Job or log stream not found"}
    }
)
def get_job_log(
    session: SessionDep,
    job_id: str
) -> StreamingResponse:
    """
    Stream log for a specific batch job.

    Args:
        session: Database session
        job_id: Job UUID

    Returns:
        Stream of log lines for the specified job

    Raises:
        HTTPException: If job or log stream not found
    """
    job = services.get_batch_job(session, job_id)
    if not job or not job.log_stream_name:
        raise HTTPException(status_code=404, detail="Job or log not found")

    return StreamingResponse(
        services.stream_batch_job_log(job.log_stream_name),
        media_type="text/plain"
    )
