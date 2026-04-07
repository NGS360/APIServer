"""
Models for the Jobs API
"""
from typing import Any, Optional
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
    id: str = Field(max_length=255, primary_key=True)
    name: str = Field(max_length=255)
    command: str = Field(max_length=1000)
    user: str = Field(max_length=100)
    submitted_on: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    log_stream_name: str | None = Field(default=None, max_length=255)
    status: JobStatus = Field(default=JobStatus.SUBMITTED)
    viewed: bool = Field(default=False)

    model_config = ConfigDict(from_attributes=True)


class BatchJobUpdate(SQLModel):
    """Schema for updating a batch job"""
    log_stream_name: Optional[str] = None
    status: Optional[JobStatus] = None
    viewed: Optional[bool] = None


class BatchJobPublic(SQLModel):
    """Schema for returning a batch job"""
    id: str
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
