"""Tests for presigned URL download endpoint and service."""

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from api.files.services import generate_presigned_url
from tests.conftest import MockS3Client


class TestGeneratePresignedUrlService:
    """Unit tests for generate_presigned_url service function."""

    def test_generate_presigned_url_success(self, mock_s3_client: MockS3Client):
        """Test successful presigned URL generation."""
        url = generate_presigned_url(
            s3_path="s3://test-bucket/path/to/file.txt",
            s3_client=mock_s3_client,
        )
        assert "test-bucket.s3.amazonaws.com" in url
        assert "path/to/file.txt" in url
        assert "X-Amz-Signature" in url

    def test_generate_presigned_url_custom_expiration(
        self, mock_s3_client: MockS3Client
    ):
        """Test presigned URL with custom expiration."""
        url = generate_presigned_url(
            s3_path="s3://test-bucket/file.bam",
            s3_client=mock_s3_client,
            expiration=7200,
        )
        assert "X-Amz-Expires=7200" in url

    def test_generate_presigned_url_default_expiration(
        self, mock_s3_client: MockS3Client
    ):
        """Test presigned URL uses default 1-hour expiration."""
        url = generate_presigned_url(
            s3_path="s3://test-bucket/file.bam",
            s3_client=mock_s3_client,
        )
        assert "X-Amz-Expires=3600" in url

    def test_generate_presigned_url_invalid_path(
        self, mock_s3_client: MockS3Client
    ):
        """Test error on invalid S3 path."""
        with pytest.raises(HTTPException) as exc_info:
            generate_presigned_url(
                s3_path="not-an-s3-path",
                s3_client=mock_s3_client,
            )
        assert exc_info.value.status_code == 400

    def test_generate_presigned_url_bucket_only(
        self, mock_s3_client: MockS3Client
    ):
        """Test error when path has no file key."""
        with pytest.raises(HTTPException) as exc_info:
            generate_presigned_url(
                s3_path="s3://bucket-only",
                s3_client=mock_s3_client,
            )
        assert exc_info.value.status_code == 400
        assert "file key" in exc_info.value.detail.lower()

    def test_generate_presigned_url_no_credentials(
        self, mock_s3_client: MockS3Client
    ):
        """Test error when AWS credentials are missing."""
        mock_s3_client.simulate_error("NoCredentialsError")
        with pytest.raises(HTTPException) as exc_info:
            generate_presigned_url(
                s3_path="s3://test-bucket/file.txt",
                s3_client=mock_s3_client,
            )
        assert exc_info.value.status_code == 401

    def test_generate_presigned_url_bucket_not_found(
        self, mock_s3_client: MockS3Client
    ):
        """Test error when S3 bucket doesn't exist."""
        mock_s3_client.simulate_error("NoSuchBucket")
        with pytest.raises(HTTPException) as exc_info:
            generate_presigned_url(
                s3_path="s3://nonexistent/file.txt",
                s3_client=mock_s3_client,
            )
        assert exc_info.value.status_code == 404

    def test_generate_presigned_url_access_denied(
        self, mock_s3_client: MockS3Client
    ):
        """Test error when access is denied."""
        mock_s3_client.simulate_error("AccessDenied")
        with pytest.raises(HTTPException) as exc_info:
            generate_presigned_url(
                s3_path="s3://restricted-bucket/secret.txt",
                s3_client=mock_s3_client,
            )
        assert exc_info.value.status_code == 403


class TestDownloadFileRoute:
    """Integration tests for GET /api/v1/files/download endpoint."""

    def test_download_returns_307_redirect(
        self, client: TestClient, mock_s3_client: MockS3Client
    ):
        """Test that download endpoint returns 307 redirect."""
        response = client.get(
            "/api/v1/files/download",
            params={"path": "s3://test-bucket/data/sample.fastq.gz"},
            follow_redirects=False,
        )
        assert response.status_code == 307
        location = response.headers["location"]
        assert "test-bucket.s3.amazonaws.com" in location
        assert "data/sample.fastq.gz" in location
        assert "X-Amz-Signature" in location

    def test_download_redirect_location_header(
        self, client: TestClient, mock_s3_client: MockS3Client
    ):
        """Test that the Location header contains a valid presigned URL."""
        response = client.get(
            "/api/v1/files/download",
            params={"path": "s3://my-bucket/path/to/report.html"},
            follow_redirects=False,
        )
        assert response.status_code == 307
        location = response.headers["location"]
        assert location.startswith("https://")
        assert "X-Amz-Expires" in location

    def test_download_missing_path_param(self, client: TestClient):
        """Test 422 error when path query param is missing."""
        response = client.get("/api/v1/files/download")
        assert response.status_code == 422

    def test_download_invalid_s3_path(
        self, client: TestClient, mock_s3_client: MockS3Client
    ):
        """Test 400 error for invalid S3 path."""
        response = client.get(
            "/api/v1/files/download",
            params={"path": "/local/path/file.txt"},
        )
        assert response.status_code == 400

    def test_download_no_credentials(
        self, client: TestClient, mock_s3_client: MockS3Client
    ):
        """Test 401 when AWS credentials are missing."""
        mock_s3_client.simulate_error("NoCredentialsError")
        response = client.get(
            "/api/v1/files/download",
            params={"path": "s3://test-bucket/file.txt"},
        )
        assert response.status_code == 401

    def test_download_access_denied(
        self, client: TestClient, mock_s3_client: MockS3Client
    ):
        """Test 403 when S3 access is denied."""
        mock_s3_client.simulate_error("AccessDenied")
        response = client.get(
            "/api/v1/files/download",
            params={"path": "s3://restricted-bucket/file.txt"},
        )
        assert response.status_code == 403

    def test_download_bucket_not_found(
        self, client: TestClient, mock_s3_client: MockS3Client
    ):
        """Test 404 when S3 bucket doesn't exist."""
        mock_s3_client.simulate_error("NoSuchBucket")
        response = client.get(
            "/api/v1/files/download",
            params={"path": "s3://nonexistent-bucket/file.txt"},
        )
        assert response.status_code == 404

    def test_download_bucket_only_no_key(
        self, client: TestClient, mock_s3_client: MockS3Client
    ):
        """Test 400 when S3 path has bucket but no file key."""
        response = client.get(
            "/api/v1/files/download",
            params={"path": "s3://test-bucket"},
        )
        assert response.status_code == 400
