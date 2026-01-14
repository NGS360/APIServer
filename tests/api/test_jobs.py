"""
Test /jobs endpoint and jobs functionality
"""

import uuid
from unittest.mock import patch, MagicMock

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session

from api.jobs.models import (
    BatchJob,
    BatchJobCreate,
    BatchJobUpdate,
    BatchJobSubmit,
    JobStatus,
    AwsBatchEnvironment,
    AwsBatchConfig,
)


###############################################################################
# Model Tests
###############################################################################


class TestJobModels:
    """Tests for job model definitions"""

    def test_job_status_enum(self):
        """Test JobStatus enum values"""
        assert JobStatus.QUEUED.value == "Queued"
        assert JobStatus.SUBMITTED.value == "Submitted"
        assert JobStatus.PENDING.value == "Pending"
        assert JobStatus.RUNNABLE.value == "Runnable"
        assert JobStatus.STARTING.value == "Starting"
        assert JobStatus.RUNNING.value == "Running"
        assert JobStatus.SUCCEEDED.value == "Succeeded"
        assert JobStatus.FAILED.value == "Failed"

    def test_batch_job_model(self):
        """Test BatchJob model creation"""
        job = BatchJob(
            name="test-job",
            command="echo hello",
            user="testuser",
            status=JobStatus.QUEUED,
        )
        assert job.name == "test-job"
        assert job.command == "echo hello"
        assert job.user == "testuser"
        assert job.status == JobStatus.QUEUED
        assert job.viewed is False
        assert job.id is not None

    def test_batch_job_create_schema(self):
        """Test BatchJobCreate schema"""
        job_create = BatchJobCreate(
            name="test-job",
            command="echo hello",
            user="testuser",
            aws_job_id="aws-123",
            status=JobStatus.SUBMITTED,
        )
        assert job_create.name == "test-job"
        assert job_create.command == "echo hello"
        assert job_create.user == "testuser"
        assert job_create.aws_job_id == "aws-123"
        assert job_create.status == JobStatus.SUBMITTED

    def test_batch_job_update_schema(self):
        """Test BatchJobUpdate schema with partial updates"""
        job_update = BatchJobUpdate(
            status=JobStatus.RUNNING,
            log_stream_name="test-stream",
        )
        assert job_update.status == JobStatus.RUNNING
        assert job_update.log_stream_name == "test-stream"
        assert job_update.name is None

    def test_aws_batch_environment_model(self):
        """Test AwsBatchEnvironment model"""
        env = AwsBatchEnvironment(
            name="MY_VAR",
            value="my_value"
        )
        assert env.name == "MY_VAR"
        assert env.value == "my_value"

    def test_aws_batch_config_minimal(self):
        """Test AwsBatchConfig with minimal required fields"""
        aws_config = AwsBatchConfig(
            job_name="test-job",
            job_definition="test-def:1",
            job_queue="test-queue",
            command="run.sh",
        )
        assert aws_config.job_name == "test-job"
        assert aws_config.job_definition == "test-def:1"
        assert aws_config.job_queue == "test-queue"
        assert aws_config.command == "run.sh"
        assert aws_config.environment is None

    def test_aws_batch_config_with_environment(self):
        """Test AwsBatchConfig with environment variables"""
        env_vars = [
            AwsBatchEnvironment(name="VAR1", value="value1"),
            AwsBatchEnvironment(name="VAR2", value="value2"),
        ]

        aws_config = AwsBatchConfig(
            job_name="test-job",
            job_definition="test-def:1",
            job_queue="test-queue",
            command="run.sh",
            environment=env_vars,
        )

        assert len(aws_config.environment) == 2
        assert aws_config.environment[0].name == "VAR1"
        assert aws_config.environment[1].value == "value2"

    def test_aws_batch_config_with_command_string(self):
        """Test AwsBatchConfig accepts command as string"""
        aws_config = AwsBatchConfig(
            job_name="test-job",
            job_definition="test-def:1",
            job_queue="test-queue",
            command="python script.py --arg",
        )
        assert aws_config.command == "python script.py --arg"

    def test_batch_job_submit_extends_config(self):
        """Test BatchJobSubmit extends AwsBatchConfig"""
        job_submit = BatchJobSubmit(
            job_name="test-job",
            job_definition="test-def:1",
            job_queue="test-queue",
            command="echo hello",
            user="testuser",
        )
        assert job_submit.job_name == "test-job"
        assert job_submit.user == "testuser"
        assert job_submit.command == "echo hello"
        assert isinstance(job_submit, AwsBatchConfig)

    def test_batch_job_submit_with_environment(self):
        """Test BatchJobSubmit with environment variables"""
        env_vars = [
            AwsBatchEnvironment(name="ENV1", value="val1"),
            AwsBatchEnvironment(name="ENV2", value="val2"),
        ]
        job_submit = BatchJobSubmit(
            job_name="test-job",
            job_definition="test-def:1",
            job_queue="test-queue",
            command="python script.py",
            environment=env_vars,
            user="testuser",
        )
        assert len(job_submit.environment) == 2
        assert job_submit.environment[0].name == "ENV1"


###############################################################################
# API Endpoint Tests
###############################################################################


class TestJobsAPI:
    """Tests for jobs API endpoints"""

    @patch("api.jobs.services.boto3.client")
    def test_submit_job(self, mock_boto_client, client: TestClient):
        """Test submitting a new job via API"""
        # Mock AWS Batch response
        mock_batch = MagicMock()
        mock_batch.submit_job.return_value = {
            "jobId": "aws-job-123",
            "jobName": "test-job",
        }
        mock_boto_client.return_value = mock_batch

        # Submit job
        job_data = {
            "job_name": "test-job",
            "job_definition": "test-def:1",
            "job_queue": "test-queue",
            "command": "echo hello",
            "user": "testuser",
        }
        response = client.post("/api/v1/jobs", json=job_data)

        assert response.status_code == 201
        data = response.json()
        assert data["name"] == "test-job"
        assert data["user"] == "testuser"
        assert data["aws_job_id"] == "aws-job-123"
        assert data["status"] == "Submitted"
        assert "id" in data

        # Verify AWS Batch was called
        mock_batch.submit_job.assert_called_once()

    @patch("api.jobs.services.boto3.client")
    def test_submit_job_with_environment(self, mock_boto_client, client: TestClient):
        """Test submitting a job with environment variables"""
        mock_batch = MagicMock()
        mock_batch.submit_job.return_value = {
            "jobId": "aws-job-456",
            "jobName": "test-job-env",
        }
        mock_boto_client.return_value = mock_batch

        job_data = {
            "job_name": "test-job-env",
            "job_definition": "test-def:1",
            "job_queue": "test-queue",
            "command": "python script.py",
            "environment": [
                {"name": "VAR1", "value": "value1"},
                {"name": "VAR2", "value": "value2"},
            ],
            "user": "testuser",
        }
        response = client.post("/api/v1/jobs", json=job_data)

        assert response.status_code == 201
        data = response.json()
        assert data["aws_job_id"] == "aws-job-456"

        # Verify container overrides include environment
        call_args = mock_batch.submit_job.call_args[1]
        assert "containerOverrides" in call_args
        env = call_args["containerOverrides"]["environment"]
        assert len(env) == 2
        assert env[0]["name"] == "VAR1"
        assert env[1]["value"] == "value2"

    def test_get_jobs_empty(self, client: TestClient):
        """Test getting jobs when none exist"""
        response = client.get("/api/v1/jobs")
        assert response.status_code == 200
        data = response.json()
        assert data["count"] == 0
        assert data["data"] == []

    @patch("api.jobs.services.boto3.client")
    def test_get_jobs_with_data(self, mock_boto_client, client: TestClient, session: Session):
        """Test getting list of jobs"""
        # Mock AWS Batch
        mock_batch = MagicMock()
        mock_batch.submit_job.return_value = {
            "jobId": "aws-job-123",
            "jobName": "test-job",
        }
        mock_boto_client.return_value = mock_batch

        # Create jobs via API
        for i in range(3):
            job_data = {
                "job_name": f"test-job-{i}",
                "job_definition": "test-def:1",
                "job_queue": "test-queue",
                "command": f"echo hello-{i}",
                "user": "testuser",
            }
            client.post("/api/v1/jobs", json=job_data)

        # Get jobs
        response = client.get("/api/v1/jobs")
        assert response.status_code == 200
        data = response.json()
        assert data["count"] == 3
        assert len(data["data"]) == 3

    @patch("api.jobs.services.boto3.client")
    def test_get_jobs_with_filters(self, mock_boto_client, client: TestClient):
        """Test filtering jobs by user and status"""
        mock_batch = MagicMock()
        mock_batch.submit_job.return_value = {
            "jobId": "aws-job-123",
            "jobName": "test-job",
        }
        mock_boto_client.return_value = mock_batch

        # Create jobs for different users
        client.post("/api/v1/jobs", json={
            "job_name": "user1-job",
            "job_definition": "test-def:1",
            "job_queue": "test-queue",
            "command": "echo hello",
            "user": "user1",
        })
        client.post("/api/v1/jobs", json={
            "job_name": "user2-job",
            "job_definition": "test-def:1",
            "job_queue": "test-queue",
            "command": "echo hello",
            "user": "user2",
        })

        # Filter by user
        response = client.get("/api/v1/jobs?user=user1")
        assert response.status_code == 200
        data = response.json()
        assert data["count"] == 1
        assert data["data"][0]["user"] == "user1"

    @patch("api.jobs.services.boto3.client")
    def test_get_job_by_id(self, mock_boto_client, client: TestClient):
        """Test getting a specific job by ID"""
        mock_batch = MagicMock()
        mock_batch.submit_job.return_value = {
            "jobId": "aws-job-123",
            "jobName": "test-job",
        }
        mock_boto_client.return_value = mock_batch

        # Create job
        response = client.post("/api/v1/jobs", json={
            "job_name": "test-job",
            "job_definition": "test-def:1",
            "job_queue": "test-queue",
            "command": "echo hello",
            "user": "testuser",
        })
        job_id = response.json()["id"]

        # Get specific job
        response = client.get(f"/api/v1/jobs/{job_id}")
        assert response.status_code == 200
        data = response.json()
        assert data["id"] == job_id
        assert data["name"] == "test-job"

    def test_get_job_not_found(self, client: TestClient):
        """Test getting a non-existent job returns 404"""
        fake_id = str(uuid.uuid4())
        response = client.get(f"/api/v1/jobs/{fake_id}")
        assert response.status_code == 404

    @patch("api.jobs.services.boto3.client")
    def test_update_job(self, mock_boto_client, client: TestClient):
        """Test updating a job"""
        mock_batch = MagicMock()
        mock_batch.submit_job.return_value = {
            "jobId": "aws-job-123",
            "jobName": "test-job",
        }
        mock_boto_client.return_value = mock_batch

        # Create job
        response = client.post("/api/v1/jobs", json={
            "job_name": "test-job",
            "job_definition": "test-def:1",
            "job_queue": "test-queue",
            "command": "echo hello",
            "user": "testuser",
        })
        job_id = response.json()["id"]

        # Update job
        update_data = {
            "status": "Running",
            "log_stream_name": "test-stream",
            "viewed": True,
        }
        response = client.put(f"/api/v1/jobs/{job_id}", json=update_data)
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "Running"
        assert data["log_stream_name"] == "test-stream"
        assert data["viewed"] is True

    @patch("api.jobs.services.boto3.client")
    def test_update_job_partial(self, mock_boto_client, client: TestClient):
        """Test partial job update"""
        mock_batch = MagicMock()
        mock_batch.submit_job.return_value = {
            "jobId": "aws-job-123",
            "jobName": "test-job",
        }
        mock_boto_client.return_value = mock_batch

        # Create job
        response = client.post("/api/v1/jobs", json={
            "job_name": "test-job",
            "job_definition": "test-def:1",
            "job_queue": "test-queue",
            "command": "echo hello",
            "user": "testuser",
        })
        job_id = response.json()["id"]
        original_user = response.json()["user"]

        # Update only status
        update_data = {"status": "Succeeded"}
        response = client.put(f"/api/v1/jobs/{job_id}", json=update_data)
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "Succeeded"
        assert data["user"] == original_user  # Unchanged

    @patch("api.jobs.services.boto3.client")
    def test_jobs_pagination(self, mock_boto_client, client: TestClient):
        """Test job list pagination"""
        mock_batch = MagicMock()
        mock_batch.submit_job.return_value = {
            "jobId": "aws-job-123",
            "jobName": "test-job",
        }
        mock_boto_client.return_value = mock_batch

        # Create 25 jobs
        for i in range(25):
            client.post("/api/v1/jobs", json={
                "job_name": f"test-job-{i}",
                "job_definition": "test-def:1",
                "job_queue": "test-queue",
                "command": f"echo hello-{i}",
                "user": "testuser",
            })

        # Get first page (default limit 100)
        response = client.get("/api/v1/jobs")
        assert response.status_code == 200
        data = response.json()
        assert data["count"] == 25

        # Get with custom limit
        response = client.get("/api/v1/jobs?limit=10")
        assert response.status_code == 200
        data = response.json()
        assert len(data["data"]) == 10
        assert data["count"] == 25

    @patch("api.jobs.services.boto3.client")
    def test_jobs_sorting(self, mock_boto_client, client: TestClient):
        """Test job list sorting by different fields"""
        import time
        mock_batch = MagicMock()
        mock_batch.submit_job.return_value = {
            "jobId": "aws-job-123",
            "jobName": "test-job",
        }
        mock_boto_client.return_value = mock_batch

        # Create jobs with different names
        client.post("/api/v1/jobs", json={
            "job_name": "zebra-job",
            "job_definition": "test-def:1",
            "job_queue": "test-queue",
            "command": "echo hello",
            "user": "testuser",
        })
        time.sleep(0.01)  # Small delay to ensure different timestamps
        client.post("/api/v1/jobs", json={
            "job_name": "alpha-job",
            "job_definition": "test-def:1",
            "job_queue": "test-queue",
            "command": "echo hello",
            "user": "testuser",
        })
        time.sleep(0.01)
        client.post("/api/v1/jobs", json={
            "job_name": "beta-job",
            "job_definition": "test-def:1",
            "job_queue": "test-queue",
            "command": "echo hello",
            "user": "testuser",
        })

        # Test default sort (submitted_on desc - most recent first)
        response = client.get("/api/v1/jobs")
        assert response.status_code == 200
        data = response.json()
        assert data["data"][0]["name"] == "beta-job"
        assert data["data"][2]["name"] == "zebra-job"

        # Test sort by name ascending
        response = client.get("/api/v1/jobs?sort_by=name&sort_order=asc")
        assert response.status_code == 200
        data = response.json()
        assert data["data"][0]["name"] == "alpha-job"
        assert data["data"][1]["name"] == "beta-job"
        assert data["data"][2]["name"] == "zebra-job"

        # Test sort by name descending
        response = client.get("/api/v1/jobs?sort_by=name&sort_order=desc")
        assert response.status_code == 200
        data = response.json()
        assert data["data"][0]["name"] == "zebra-job"
        assert data["data"][2]["name"] == "alpha-job"

        # Test sort by submitted_on ascending (oldest first)
        response = client.get("/api/v1/jobs?sort_by=submitted_on&sort_order=asc")
        assert response.status_code == 200
        data = response.json()
        assert data["data"][0]["name"] == "zebra-job"
        assert data["data"][2]["name"] == "beta-job"


###############################################################################
# Service Layer Tests
###############################################################################


class TestJobsServices:
    """Tests for jobs service layer"""

    def test_create_batch_job(self, session: Session):
        """Test creating a batch job in database"""
        from api.jobs.services import create_batch_job

        job_create = BatchJobCreate(
            name="test-job",
            command="echo hello",
            user="testuser",
            aws_job_id="aws-123",
            status=JobStatus.SUBMITTED,
        )
        job = create_batch_job(session, job_create)

        assert job.id is not None
        assert job.name == "test-job"
        assert job.aws_job_id == "aws-123"
        assert job.status == JobStatus.SUBMITTED

    def test_get_batch_job(self, session: Session):
        """Test retrieving a batch job by ID"""
        from api.jobs.services import create_batch_job, get_batch_job

        # Create job
        job_create = BatchJobCreate(
            name="test-job",
            command="echo hello",
            user="testuser",
        )
        created_job = create_batch_job(session, job_create)

        # Retrieve job
        retrieved_job = get_batch_job(session, created_job.id)
        assert retrieved_job.id == created_job.id
        assert retrieved_job.name == "test-job"

    def test_get_batch_job_not_found(self, session: Session):
        """Test retrieving non-existent job raises HTTPException"""
        from api.jobs.services import get_batch_job
        from fastapi import HTTPException

        fake_id = uuid.uuid4()
        with pytest.raises(HTTPException) as exc_info:
            get_batch_job(session, fake_id)
        assert exc_info.value.status_code == 404

    def test_get_batch_jobs_with_filters(self, session: Session):
        """Test getting jobs with filters"""
        from api.jobs.services import create_batch_job, get_batch_jobs

        # Create multiple jobs
        for i in range(5):
            job_create = BatchJobCreate(
                name=f"job-{i}",
                command=f"echo {i}",
                user="user1" if i < 3 else "user2",
                status=JobStatus.SUBMITTED if i < 2 else JobStatus.RUNNING,
            )
            create_batch_job(session, job_create)

        # Filter by user
        jobs, count = get_batch_jobs(session, user="user1")
        assert count == 3

        # Filter by status
        jobs, count = get_batch_jobs(session, status_filter=JobStatus.RUNNING)
        assert count == 3

        # Both filters
        jobs, count = get_batch_jobs(
            session, user="user2", status_filter=JobStatus.RUNNING
        )
        assert count == 2

    def test_update_batch_job(self, session: Session):
        """Test updating a batch job"""
        from api.jobs.services import create_batch_job, update_batch_job

        # Create job
        job_create = BatchJobCreate(
            name="test-job",
            command="echo hello",
            user="testuser",
            status=JobStatus.SUBMITTED,
        )
        job = create_batch_job(session, job_create)

        # Update job
        job_update = BatchJobUpdate(
            status=JobStatus.RUNNING,
            log_stream_name="test-stream",
        )
        updated_job = update_batch_job(session, job.id, job_update)

        assert updated_job.status == JobStatus.RUNNING
        assert updated_job.log_stream_name == "test-stream"
        assert updated_job.name == "test-job"  # Unchanged

    @patch("api.jobs.services.boto3.client")
    def test_submit_batch_job(self, mock_boto_client, session: Session):
        """Test submit_batch_job creates database record"""
        from api.jobs.services import submit_batch_job

        # Mock AWS Batch
        mock_batch = MagicMock()
        mock_batch.submit_job.return_value = {
            "jobId": "aws-job-123",
            "jobName": "test-job",
        }
        mock_boto_client.return_value = mock_batch

        # Submit job
        container_overrides = {
            "command": ["echo", "hello"],
            "environment": [{"name": "VAR1", "value": "val1"}],
        }
        job = submit_batch_job(
            session=session,
            job_name="test-job",
            container_overrides=container_overrides,
            job_def="test-def:1",
            job_queue="test-queue",
            user="testuser",
        )

        assert job.id is not None
        assert job.name == "test-job"
        assert job.aws_job_id == "aws-job-123"
        assert job.status == JobStatus.SUBMITTED
        assert job.user == "testuser"
        assert "echo hello" in job.command

    @patch("api.jobs.services.boto3.client")
    def test_submit_batch_job_aws_error(self, mock_boto_client, session: Session):
        """Test submit_batch_job handles AWS errors"""
        from api.jobs.services import submit_batch_job
        from fastapi import HTTPException
        import botocore.exceptions

        # Mock AWS Batch to raise error
        mock_batch = MagicMock()
        mock_batch.submit_job.side_effect = botocore.exceptions.ClientError(
            {"Error": {"Code": "InvalidParameterException"}}, "submit_job"
        )
        mock_boto_client.return_value = mock_batch

        # Submit job should raise HTTPException
        with pytest.raises(HTTPException) as exc_info:
            submit_batch_job(
                session=session,
                job_name="test-job",
                container_overrides={"command": ["echo", "hello"]},
                job_def="test-def:1",
                job_queue="test-queue",
                user="testuser",
            )
        assert exc_info.value.status_code == 500
