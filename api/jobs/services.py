"""
Services for managing batch jobs.
"""
from typing import List
from sqlmodel import select, Session, func
from fastapi import HTTPException, status
import uuid

from core.logger import logger
from api.jobs.models import (
    BatchJob,
    BatchJobCreate,
    BatchJobUpdate,
    JobStatus
)


def create_batch_job(session: Session, job_in: BatchJobCreate) -> BatchJob:
    """
    Create a new batch job.
    
    Args:
        session: Database session
        job_in: Job creation data
        
    Returns:
        Created BatchJob instance
    """
    job = BatchJob.model_validate(job_in)
    session.add(job)
    session.commit()
    session.refresh(job)
    logger.info(f"Created batch job: {job.id}")
    return job


def get_batch_job(session: Session, job_id: uuid.UUID) -> BatchJob:
    """
    Retrieve a batch job by ID.
    
    Args:
        session: Database session
        job_id: Job UUID
        
    Returns:
        BatchJob instance
        
    Raises:
        HTTPException: If job not found
    """
    job = session.get(BatchJob, job_id)
    if not job:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Batch job {job_id} not found"
        )
    return job


def get_batch_jobs(
    session: Session,
    skip: int = 0,
    limit: int = 100,
    user: str | None = None,
    status_filter: JobStatus | None = None
) -> tuple[List[BatchJob], int]:
    """
    Retrieve a list of batch jobs with optional filtering.
    
    Args:
        session: Database session
        skip: Number of records to skip
        limit: Maximum number of records to return
        user: Optional user filter
        status_filter: Optional status filter
        
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
    
    # Get paginated results
    query = query.offset(skip).limit(limit).order_by(BatchJob.submitted_on.desc())
    jobs = session.exec(query).all()
    
    return jobs, total_count


def update_batch_job(
    session: Session,
    job_id: uuid.UUID,
    job_update: BatchJobUpdate
) -> BatchJob:
    """
    Update a batch job.
    
    Args:
        session: Database session
        job_id: Job UUID
        job_update: Job update data
        
    Returns:
        Updated BatchJob instance
        
    Raises:
        HTTPException: If job not found
    """
    job = get_batch_job(session, job_id)
    
    update_data = job_update.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(job, key, value)
    
    session.add(job)
    session.commit()
    session.refresh(job)
    logger.info(f"Updated batch job: {job_id}")
    return job
