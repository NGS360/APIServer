"""
Models for the Jobs API
"""
from typing import Any, Optional
import uuid
from datetime import datetime, timezone
from enum import Enum
from sqlmodel import SQLModel, Field
from pydantic import BaseModel, ConfigDict


class JobStatus(str, Enum):
    """Enumeration of valid batch job statuses"""
    SUBMITTED = "SUBMITTED"
    PENDING = "PENDING"
    RUNNABLE = "RUNNABLE"
    STARTING = "STARTING"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"


class BatchJob(SQLModel, table=True):
    """
    This class/table represents a batch job
    """
    id: uuid.UUID | None = Field(default_factory=uuid.uuid4, primary_key=True)
    name: str = Field(max_length=255)
    command: str = Field(max_length=1000)
    user: str = Field(max_length=100)
    submitted_on: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    aws_job_id: str | None = Field(default=None, max_length=255)
    log_stream_name: str | None = Field(default=None, max_length=255)
    status: JobStatus = Field(default=JobStatus.SUBMITTED)
    viewed: bool = Field(default=False)

    model_config = ConfigDict(from_attributes=True)


class BatchJobCreate(SQLModel):
    """Schema for creating a new batch job"""
    name: str
    command: str
    user: str
    aws_job_id: Optional[str] = None
    log_stream_name: Optional[str] = None
    status: Optional[JobStatus] = JobStatus.SUBMITTED


class BatchJobUpdate(SQLModel):
    """Schema for updating a batch job"""
    name: Optional[str] = None
    command: Optional[str] = None
    aws_job_id: Optional[str] = None
    log_stream_name: Optional[str] = None
    status: Optional[JobStatus] = JobStatus.SUBMITTED
    viewed: Optional[bool] = None


class BatchJobPublic(SQLModel):
    """Schema for returning a batch job"""
    id: uuid.UUID
    name: str
    command: str
    user: str
    submitted_on: datetime
    aws_job_id: str | None
    log_stream_name: str | None
    status: JobStatus
    viewed: bool

    model_config = ConfigDict(from_attributes=True)


class BatchJobsPublic(SQLModel):
    """Schema for returning multiple batch jobs"""
    data: list[BatchJobPublic]
    count: int


class AwsBatchEnvironment(SQLModel):
    """Schema for AWS Batch environment variable"""
    name: str
    value: str


class AwsBatchConfig(SQLModel):
    """Base schema for AWS Batch job configuration"""
    job_name: str
    job_definition: str
    job_queue: str
    command: str
    environment: Optional[list[AwsBatchEnvironment]] = None


class BatchJobSubmit(AwsBatchConfig):
    """Schema for submitting a new batch job to AWS Batch (extends AwsBatchConfig)"""
    user: str


class BatchJobConfigInput(BaseModel):
    """
    This is used to interpolate values into the AWS Batch
    job configuration when submitting a job
    """
    name: str
    desc: str
    type: str
    required: bool
    default: Optional[Any] = None


class VendorIngestionConfig(SQLModel):
    inputs: list[BatchJobConfigInput]
    aws_batch: AwsBatchConfig
