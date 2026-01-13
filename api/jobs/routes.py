"""
Routes/endpoints for the Jobs API

HTTP   URI                  Action
----   ---                  ------
GET    /api/v1/jobs         Retrieve a list of batch jobs
POST   /api/v1/jobs         Create a new batch job
GET    /api/v1/jobs/[id]    Retrieve info about a specific job
PUT    /api/v1/jobs/[id]    Update a batch job
DELETE /api/v1/jobs/[id]    Delete a batch job
"""

from typing import Optional
from fastapi import APIRouter, Query, status
from core.deps import SessionDep
from api.jobs.models import (
    BatchJobCreate,
    BatchJobUpdate,
    BatchJobPublic,
    BatchJobsPublic,
    JobStatus
)
from api.jobs import services
import uuid

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
def create_job(
    session: SessionDep,
    job_in: BatchJobCreate,
) -> BatchJobPublic:
    """
    Create a new batch job.
    
    Args:
        session: Database session
        job_in: Job creation data
        
    Returns:
        Created job information
    """
    job = services.create_batch_job(session, job_in)
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
) -> BatchJobsPublic:
    """
    Retrieve a list of batch jobs with optional filtering.
    
    Args:
        session: Database session
        skip: Number of records to skip
        limit: Maximum number of records to return
        user: Optional user filter
        status_filter: Optional status filter
        
    Returns:
        List of jobs and total count
    """
    jobs, total_count = services.get_batch_jobs(
        session, skip, limit, user, status_filter
    )
    return BatchJobsPublic(
        data=[BatchJobPublic.model_validate(job) for job in jobs],
        count=total_count
    )


@router.get(
    "/{job_id}",
    response_model=BatchJobPublic,
    tags=["Job Endpoints"],
)
def get_job(
    session: SessionDep,
    job_id: uuid.UUID,
) -> BatchJobPublic:
    """
    Retrieve information about a specific batch job.
    
    Args:
        session: Database session
        job_id: Job UUID
        
    Returns:
        Job information
    """
    job = services.get_batch_job(session, job_id)
    return BatchJobPublic.model_validate(job)


@router.put(
    "/{job_id}",
    response_model=BatchJobPublic,
    tags=["Job Endpoints"],
)
def update_job(
    session: SessionDep,
    job_id: uuid.UUID,
    job_update: BatchJobUpdate,
) -> BatchJobPublic:
    """
    Update a batch job.
    
    Args:
        session: Database session
        job_id: Job UUID
        job_update: Job update data
        
    Returns:
        Updated job information
    """
    job = services.update_batch_job(session, job_id, job_update)
    return BatchJobPublic.model_validate(job)

