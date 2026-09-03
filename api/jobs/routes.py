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
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from core.deps import SessionDep
from core.models import HTTPErrorResponse
from api.jobs.models import (
    BatchJobSubmit,
    BatchJobUpdate,
    BatchJobPublic,
    BatchJobsPublic,
    JobStatus,
    LogResponse
)
from api.jobs import services
from api.rbac.deps import AuthzDep, decide
from api.rbac.permissions import Permission
from api.rbac.resolver import AuthzContext

router = APIRouter(prefix="/jobs", tags=["Job Endpoints"])


# Fields on BatchJobUpdate that represent pipeline writeback rather than a user
# action. `viewed` is deliberately not one of them -- see require_job_update.
WRITEBACK_FIELDS = frozenset({"status", "log_stream_name"})


def require_job_update(
    request: Request, authz: AuthzDep, job_update: BatchJobUpdate
) -> AuthzContext:
    """
    Guard PUT /jobs/{job_id}, taking the requirement from the payload.

    This one route carries two operations with very different privilege:

    * The Omics and Batch event Lambdas write `status` and `log_stream_name` back
      as a job progresses. That is machine writeback -- `job:update`, held only by
      service_account, platform_admin and admin.
    * The web UI sends `{"viewed": true}` when someone opens a job from the
      notifications dropdown (see useViewJob in frontend-ui). Every signed-in user
      does that, so `member` has to be able to.

    Guarding the whole route on `job:update` would therefore deny an ordinary
    click: production carried 17 such requests from 7 users alongside 87 machine
    writebacks in a single day, and `member` holds job:read and job:submit but not
    job:update. So a payload touching only `viewed` is checked against `job:read`
    instead -- if you may see the job, you may record that you saw it. Anything
    reaching a writeback field needs `job:update`, including a payload that sets
    both.

    The field set is matched against `model_dump(exclude_unset=True)`, which is
    exactly what update_batch_job persists, so the check cannot drift from the
    write: naming a writeback field at all requires the permission, even if the
    value sent is null.

    Declaring the body model here as well as on the handler is deliberate and
    supported -- FastAPI parses it once, the handler still receives it, and the
    OpenAPI schema is unchanged, so the generated frontend client does not move.
    """
    supplied = set(job_update.model_dump(exclude_unset=True))
    permission = (
        Permission.JOB_UPDATE if WRITEBACK_FIELDS & supplied
        else Permission.JOB_READ
    )
    decide(request, authz.has(permission), (permission,), scope=None)
    return authz


# Tagged like the require_permission factories so the route-coverage test and any
# future "what does this endpoint need" introspection see both possibilities.
require_job_update.rbac_permissions = (
    Permission.JOB_UPDATE, Permission.JOB_READ,
)
require_job_update.rbac_plane = "global"


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
        project_id=job_in.project_id,
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
    project_id: Optional[str] = Query(
        None, description="Filter by owning project (Project.project_id, e.g. P-19900109-0001)"
    ),
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
        project_id: Optional project filter
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
        project_id=project_id,
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
        404: {"model": HTTPErrorResponse, "description": "Job not found"}
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
    dependencies=[Depends(require_job_update)],
    responses={
        404: {"model": HTTPErrorResponse, "description": "Job not found"}
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
    response_model=list[str],
    tags=["Job Endpoints"],
    responses={
        404: {"model": HTTPErrorResponse, "description": "Job not found"}
    }
)
def get_job_log(
    session: SessionDep,
    job_id: str,
) -> list[str]:
    """
    Retrieve log for a specific batch job.

    Args:
        session: Database session
        job_id: Job UUID

    Returns:
        Log output as a list of strings
    """
    logs = services.get_batch_job_log(session, job_id)
    return logs


@router.get(
    "/{job_id}/log/paginated",
    response_model=LogResponse,
    tags=["Job Endpoints"],
    responses={
        404: {"model": HTTPErrorResponse, "description": "Job not found"}
    }
)
def get_job_log_paginated(
    session: SessionDep,
    job_id: str,
    limit: int = Query(1000, ge=1, le=10000, description="Number of log lines to return"),
    next_token: Optional[str] = Query(None, description="Token for next page of results"),
    start_from_head: bool = Query(True, description="Start from beginning (true) or end (false)"),
) -> LogResponse:
    """
    Get paginated logs for a specific batch job.

    This endpoint returns logs in pages, allowing clients to fetch large log files
    incrementally without timeouts.

    Args:
        session: Database session
        job_id: Job UUID
        limit: Maximum number of log lines to return (1-10000)
        next_token: Pagination token from previous response
        start_from_head: If true, start from oldest logs; if false, start from newest

    Returns:
        Paginated log response with events and next_token for subsequent requests

    Example usage:
        1. First request: GET /jobs/{id}/log/paginated?limit=1000
        2. Next page: GET /jobs/{id}/log/paginated?limit=1000&next_token={token}
    """
    job = services.get_batch_job(session, job_id)
    if not job or not job.log_stream_name:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Job or log not found"
        )

    return services.get_batch_job_log_paginated(
        log_stream_name=job.log_stream_name,
        limit=limit,
        next_token=next_token,
        start_from_head=start_from_head
    )
