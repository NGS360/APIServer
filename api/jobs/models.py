"""
Models for the Jobs API
"""
from typing import Optional
import uuid
from datetime import datetime
from enum import Enum
from sqlmodel import SQLModel, Field
from pydantic import ConfigDict


class JobStatus(str, Enum):
    """Enumeration of valid batch job statuses"""
    QUEUED = "Queued"
    SUBMITTED = "Submitted"
    PENDING = "Pending"
    RUNNABLE = "Runnable"
    STARTING = "Starting"
    RUNNING = "Running"
    SUCCEEDED = "Succeeded"
    FAILED = "Failed"


class BatchJob(SQLModel, table=True):
    """
    This class/table represents a batch job
    """
    id: uuid.UUID | None = Field(default_factory=uuid.uuid4, primary_key=True)
    name: str = Field(max_length=255)
    command: str = Field(max_length=1000)
    user: str = Field(max_length=100)
    submitted_on: datetime = Field(default_factory=datetime.utcnow)
    log_stream_name: str | None = Field(default=None, max_length=255)
    status: JobStatus = Field(default=JobStatus.QUEUED)
    viewed: bool = Field(default=False)

    model_config = ConfigDict(from_attributes=True)


class BatchJobCreate(SQLModel):
    """Schema for creating a new batch job"""
    name: str
    command: str
    user: str
    log_stream_name: Optional[str] = None
    status: Optional[JobStatus] = JobStatus.QUEUED


class BatchJobUpdate(SQLModel):
    """Schema for updating a batch job"""
    name: Optional[str] = None
    command: Optional[str] = None
    log_stream_name: Optional[str] = None
    status: Optional[JobStatus] = None
    viewed: Optional[bool] = None


class BatchJobPublic(SQLModel):
    """Schema for returning a batch job"""
    id: uuid.UUID
    name: str
    command: str
    user: str
    submitted_on: datetime
    log_stream_name: str | None
    status: JobStatus
    viewed: bool

    model_config = ConfigDict(from_attributes=True)


class BatchJobsPublic(SQLModel):
    """Schema for returning multiple batch jobs"""
    data: list[BatchJobPublic]
    count: int
