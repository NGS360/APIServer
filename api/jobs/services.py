"""
Services for managing batch jobs.
"""
from typing import Any, List, Dict, Literal
from sqlmodel import select, Session, func
from fastapi import HTTPException, status
import boto3
import botocore
from core.config import get_settings
from core.logger import logger

from api.jobs.models import (
    BatchJob,
    BatchJobUpdate,
    JobStatus
)


def get_batch_job(session: Session, job_id: str) -> BatchJob | None:
    """
    Retrieve a batch job by ID.

    Args:
        session: Database session
        job_id: Job UUID

    Returns:
        BatchJob instance or None if not found
    """
    return session.get(BatchJob, job_id)


def get_batch_jobs(
    session: Session,
    skip: int = 0,
    limit: int = 100,
    user: str | None = None,
    status_filter: JobStatus | None = None,
    sort_by: str = "submitted_on",
    sort_order: Literal["asc", "desc"] = "desc"
) -> tuple[List[BatchJob], int]:
    """
    Retrieve a list of batch jobs with optional filtering.

    Args:
        session: Database session
        skip: Number of records to skip
        limit: Maximum number of records to return
        user: Optional user filter
        status_filter: Optional status filter
        sort_by: Field to sort by (defaults to 'submitted_on')
        sort_order: Sort order 'asc' or 'desc' (defaults to 'desc')

    Returns:
        Tuple of (list of BatchJob instances, total count)
    """
    query = select(BatchJob)

    if user:
        query = query.where(BatchJob.user == user)
    if status_filter:
        query = query.where(BatchJob.status == status_filter)

    # Get total count
    count_query = select(func.count()).select_from(query.subquery())
    total_count = session.exec(count_query).one()

    # Determine sort field and direction
    sort_field = getattr(BatchJob, sort_by, BatchJob.submitted_on)
    sort_direction = sort_field.asc() if sort_order == "asc" else sort_field.desc()

    # Get paginated results
    query = query.offset(skip).limit(limit).order_by(sort_direction)
    jobs = session.exec(query).all()

    return jobs, total_count


def update_batch_job(
    session: Session,
    job: BatchJob,
    job_update: BatchJobUpdate
) -> BatchJob:
    """
    Update a batch job.

    Args:
        session: Database session
        job: BatchJob instance to update
        job_update: Job update data

    Returns:
        Updated BatchJob instance

    Raises:
        HTTPException: If job not found
    """
    update_data = job_update.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(job, key, value)

    session.add(job)
    session.commit()
    session.refresh(job)
    logger.info(f"Updated batch job: {job.id}")
    return job


def submit_batch_job(
    session: Session,
    job_name: str,
    container_overrides: Dict[str, Any],
    job_def: str,
    job_queue: str,
    user: str
) -> BatchJob:
    """
    Submit a job to AWS Batch and create a database record for tracking.

    Args:
        session: Database session for retrieving AWS settings
        job_name: Name of the job to submit
        container_overrides: Container configuration overrides
        job_def: Job definition name
        job_queue: Job queue name
        user: User submitting the job

    Returns:
        BatchJob: The created database record with AWS job information
    """
    logger.info(
        f"Submitting job '{job_name}' to AWS Batch queue '{job_queue}' "
        f"with definition '{job_def}'"
    )

    # Extract command from container overrides (expecting list)
    command = " ".join(container_overrides.get("command", []))

    # Auto-inject API endpoint so worker containers know where to call back
    settings = get_settings()
    container_overrides.setdefault("environment", [])
    container_overrides["environment"].append(
        {"name": "NGS360_API_ENDPOINT", "value": settings.client_origin}
    )
    logger.info(f"Container overrides: {container_overrides}")

    try:
        batch_client = boto3.client("batch", region_name=settings.AWS_REGION)
        response = batch_client.submit_job(
            jobName=job_name,
            jobQueue=job_queue,
            jobDefinition=job_def,
            containerOverrides=container_overrides,
        )
    except botocore.exceptions.ClientError as err:
        logger.error(f"Failed to submit job to AWS Batch: {err}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to submit job to AWS Batch: {err}",
        ) from err

    job = BatchJob(
        id=response.get("jobId"),
        name=job_name,
        command=command,
        user=user,
        status=JobStatus.SUBMITTED
    )
    session.add(job)
    session.commit()
    session.refresh(job)
    logger.info(f"Created batch job: {job.id}")

    return job


# def get_batch_job_log(session: Session, job_id: uuid.UUID) -> list[str]:
#     """
#     Retrieve the log output for a batch job.

#     Args:
#         session: Database session
#         job_id: Job UUID
#     Returns:
#         Log output as a list of strings
#     """
#     job = session.get(BatchJob, job_id)

#     if not job or not job.log_stream_name:
#         logger.warning(f"Job {job_id} not available or does not have a log stream name")
#         return []

#     log_group = "/aws/batch/job"
#     log_stream_name = job.log_stream_name

#     logger.info(f"Retrieving logs for job {job_id} from log group '{log_group}' "
#                 f"and stream '{log_stream_name}'")
#     return get_log_events(log_group, log_stream_name)


# def get_log_events(log_group, log_stream_name, start_time=None, end_time=None):
#     """
#     List events from CloudWatch log
#     """
#     kwargs = {
#         'logGroupName': log_group,
#         'logStreamName': log_stream_name,
#         'limit': 10000,
#         'startFromHead': True,
#     }

#     if start_time:
#         kwargs['startTime'] = start_time
#     if end_time:
#         kwargs['endTime'] = end_time

#     events = []
#     while True:
#         try:
#             resp = boto3.client(
#                 'logs',
#                 region_name=get_settings().AWS_REGION
#             ).get_log_events(**kwargs)
#         except botocore.exceptions.ClientError:
#             return ["No log (yet) available"]
#         for event in resp['events']:
#             events.append(event['message'])

#         next_forward_token = resp.get('nextForwardToken')
#         if not next_forward_token or kwargs.get('nextToken') == next_forward_token:
#             break
#         kwargs['nextToken'] = next_forward_token
#     return events


def stream_batch_job_log(log_stream_name: str):
    """Stream log events to avoid memory buildup and timeouts."""
    log_group = "/aws/batch/job"
    settings = get_settings()

    # Create client ONCE outside loop
    logs_client = boto3.client('logs', region_name=settings.AWS_REGION)

    kwargs = {
        'logGroupName': log_group,
        'logStreamName': log_stream_name,
        'limit': 1000,  # Smaller batches for faster initial response
        'startFromHead': True,
    }

    logger.info(f"Starting log stream for {log_stream_name}")
    try:
        consecutive_empty = 0
        max_empty_attempts = 3  # Stop after 3 consecutive empty responses

        while True:
            resp = logs_client.get_log_events(**kwargs)
            events = resp.get('events', [])

            # Yield all events
            if events:
                consecutive_empty = 0  # Reset counter on new events
                for event in events:
                    yield event['message'] + '\n'
            else:
                consecutive_empty += 1
                logger.debug(f"Empty response #{consecutive_empty} for {log_stream_name}")

                # Stop if we get too many empty responses
                if consecutive_empty >= max_empty_attempts:
                    logger.info(f"No more events after {consecutive_empty} attempts")
                    break

            # Check pagination token for next batch
            next_token = resp.get('nextForwardToken')
            prev_token = kwargs.get('nextToken')
            logger.debug(f"prev_token={prev_token}, next_token={next_token}")

            # Exit conditions:
            # 1. No next token provided
            # 2. Token hasn't changed (no more data)
            if not next_token or prev_token == next_token:
                logger.info("Pagination complete (token unchanged)")
                break

            kwargs['nextToken'] = next_token

    except botocore.exceptions.ClientError as e:
        yield f"Error retrieving logs: {str(e)}\n"

    logger.info(f"Completed log stream for {log_stream_name}")
