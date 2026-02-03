"""
Test /manifest endpoint
"""

from datetime import datetime
from unittest.mock import MagicMock
import io
import pytest

from fastapi import HTTPException
from fastapi.testclient import TestClient

from api.manifest.services import _parse_s3_path
from api.manifest.services import get_latest_manifest_file

from tests.conftest import MockS3Client


class TestManifestServices:
    """Test manifest service functions"""

    def test_parse_s3_path(self):
        """Test S3 path parsing in manifest service"""

        # Valid paths
        assert _parse_s3_path("s3://my-bucket") == ("my-bucket", "")
        assert _parse_s3_path("s3://my-bucket/") == ("my-bucket", "")
        assert _parse_s3_path("s3://my-bucket/manifests") == ("my-bucket", "manifests")
        assert _parse_s3_path("s3://my-bucket/vendor/manifests/") == (
            "my-bucket",
            "vendor/manifests/",
        )

        # Invalid paths
        invalid_paths = [
            "http://my-bucket",
            "s3:/my-bucket",
            "s3://",
            "s3:///",
            "s3://my-bucket//prefix",
        ]
        for path in invalid_paths:
            try:
                _parse_s3_path(path)
                assert False, f"Expected ValueError for path: {path}"
            except ValueError:
                pass  # Expected

    def test_get_latest_manifest_file_single(self, mock_s3_client: MockS3Client):
        """Test finding latest manifest when only one exists"""
        # Setup mock S3 with one manifest file
        files = [
            {
                "Key": "vendor/Sample_Manifest.csv",
                "LastModified": datetime(2024, 1, 1, 12, 0, 0),
                "Size": 1024,
            }
        ]
        mock_s3_client.setup_bucket("test-bucket", "vendor/", files, [])

        result = get_latest_manifest_file("s3://test-bucket/vendor/", mock_s3_client)

        assert result == "s3://test-bucket/vendor/Sample_Manifest.csv"

    def test_get_latest_manifest_file_multiple(self, mock_s3_client: MockS3Client):
        """Test finding latest manifest when multiple exist"""
        # Setup mock S3 with multiple manifest files - most recent should be selected
        files = [
            {
                "Key": "vendor/Old_Manifest.csv",
                "LastModified": datetime(2024, 1, 1, 12, 0, 0),
                "Size": 1024,
            },
            {
                "Key": "vendor/Latest_Manifest.csv",
                "LastModified": datetime(2024, 3, 15, 12, 0, 0),
                "Size": 2048,
            },
            {
                "Key": "vendor/Middle_Manifest.csv",
                "LastModified": datetime(2024, 2, 1, 12, 0, 0),
                "Size": 1536,
            },
        ]
        mock_s3_client.setup_bucket("test-bucket", "vendor/", files, [])

        result = get_latest_manifest_file("s3://test-bucket/vendor/", mock_s3_client)

        assert result == "s3://test-bucket/vendor/Latest_Manifest.csv"

    def test_get_latest_manifest_case_insensitive(self, mock_s3_client: MockS3Client):
        """Test case-insensitive matching for 'Manifest'"""
        # Test various cases: MANIFEST, manifest, Manifest, etc.
        files = [
            {
                "Key": "vendor/sample_MANIFEST.csv",
                "LastModified": datetime(2024, 1, 1, 12, 0, 0),
                "Size": 1024,
            },
            {
                "Key": "vendor/data_manifest.csv",
                "LastModified": datetime(2024, 1, 2, 12, 0, 0),
                "Size": 1024,
            },
            {
                "Key": "vendor/export_ManiFest.csv",
                "LastModified": datetime(2024, 1, 3, 12, 0, 0),
                "Size": 1024,
            },
        ]
        mock_s3_client.setup_bucket("test-bucket", "vendor/", files, [])

        result = get_latest_manifest_file("s3://test-bucket/vendor/", mock_s3_client)

        # Should find the most recent one (export_ManiFest.csv)
        assert result == "s3://test-bucket/vendor/export_ManiFest.csv"

    def test_get_latest_manifest_csv_only(self, mock_s3_client: MockS3Client):
        """Test that only .csv files are matched"""
        # Include non-CSV files with manifest in name
        files = [
            {
                "Key": "vendor/Manifest.txt",
                "LastModified": datetime(2024, 1, 5, 12, 0, 0),
                "Size": 1024,
            },
            {
                "Key": "vendor/Manifest.xlsx",
                "LastModified": datetime(2024, 1, 4, 12, 0, 0),
                "Size": 2048,
            },
            {
                "Key": "vendor/Manifest.csv",
                "LastModified": datetime(2024, 1, 1, 12, 0, 0),
                "Size": 512,
            },
            {
                "Key": "vendor/Manifest_backup.csv.bak",
                "LastModified": datetime(2024, 1, 6, 12, 0, 0),
                "Size": 512,
            },
        ]
        mock_s3_client.setup_bucket("test-bucket", "vendor/", files, [])

        result = get_latest_manifest_file("s3://test-bucket/vendor/", mock_s3_client)

        # Should only find the .csv file
        assert result == "s3://test-bucket/vendor/Manifest.csv"

    def test_get_latest_manifest_substring_match(self, mock_s3_client: MockS3Client):
        """Test substring matching for 'manifest' in filename"""

        # Files with manifest as substring
        files = [
            {
                "Key": "vendor/SampleManifest.csv",
                "LastModified": datetime(2024, 1, 1, 12, 0, 0),
                "Size": 1024,
            },
            {
                "Key": "vendor/manifest_export.csv",
                "LastModified": datetime(2024, 1, 2, 12, 0, 0),
                "Size": 1024,
            },
            {
                "Key": "vendor/daily_manifest_file.csv",
                "LastModified": datetime(2024, 1, 3, 12, 0, 0),
                "Size": 1024,
            },
        ]
        mock_s3_client.setup_bucket("test-bucket", "vendor/", files, [])

        result = get_latest_manifest_file("s3://test-bucket/vendor/", mock_s3_client)

        # Should find the most recent one
        assert result == "s3://test-bucket/vendor/daily_manifest_file.csv"

    def test_get_latest_manifest_recursive(self, mock_s3_client: MockS3Client):
        """Test recursive search through subdirectories"""
        # Files in different subdirectories
        files = [
            {
                "Key": "vendor/2024/01/Manifest.csv",
                "LastModified": datetime(2024, 1, 1, 12, 0, 0),
                "Size": 1024,
            },
            {
                "Key": "vendor/2024/02/Manifest.csv",
                "LastModified": datetime(2024, 2, 1, 12, 0, 0),
                "Size": 1024,
            },
            {
                "Key": "vendor/2024/03/Manifest.csv",
                "LastModified": datetime(2024, 3, 1, 12, 0, 0),
                "Size": 1024,
            },
            {
                "Key": "vendor/archive/old_manifest.csv",
                "LastModified": datetime(2023, 12, 1, 12, 0, 0),
                "Size": 512,
            },
        ]
        mock_s3_client.setup_bucket("test-bucket", "vendor/", files, [])

        result = get_latest_manifest_file("s3://test-bucket/vendor/", mock_s3_client)

        # Should find the most recent across all subdirectories
        assert result == "s3://test-bucket/vendor/2024/03/Manifest.csv"

    def test_get_latest_manifest_no_match(self, mock_s3_client: MockS3Client):
        """Test returning None when no manifest files found"""
        # Files without "manifest" in name
        files = [
            {
                "Key": "vendor/data.csv",
                "LastModified": datetime(2024, 1, 1, 12, 0, 0),
                "Size": 1024,
            },
            {
                "Key": "vendor/export.csv",
                "LastModified": datetime(2024, 1, 2, 12, 0, 0),
                "Size": 1024,
            },
        ]
        mock_s3_client.setup_bucket("test-bucket", "vendor/", files, [])

        result = get_latest_manifest_file("s3://test-bucket/vendor/", mock_s3_client)

        assert result is None

    def test_get_latest_manifest_empty_bucket(self, mock_s3_client: MockS3Client):
        """Test returning None when bucket/prefix is empty"""
        # Empty bucket
        mock_s3_client.setup_bucket("test-bucket", "vendor/", [], [])

        result = get_latest_manifest_file("s3://test-bucket/vendor/", mock_s3_client)

        assert result is None

    def test_get_latest_manifest_invalid_path(self, mock_s3_client: MockS3Client):
        """Test error handling for invalid S3 path"""
        invalid_paths = ["http://bucket/path", "s3://", "s3:///bucket"]

        for path in invalid_paths:
            with pytest.raises(HTTPException) as exc_info:
                get_latest_manifest_file(path, mock_s3_client)
            assert exc_info.value.status_code == 400

    def test_get_latest_manifest_no_credentials(self, mock_s3_client: MockS3Client):
        """Test error handling when AWS credentials are missing"""
        mock_s3_client.simulate_error("NoCredentialsError")

        with pytest.raises(HTTPException) as exc_info:
            get_latest_manifest_file("s3://test-bucket/vendor/", mock_s3_client)
        assert exc_info.value.status_code == 401

    def test_get_latest_manifest_bucket_not_found(self, mock_s3_client: MockS3Client):
        """Test error handling when bucket doesn't exist"""
        mock_s3_client.simulate_error("NoSuchBucket")

        with pytest.raises(HTTPException) as exc_info:
            get_latest_manifest_file("s3://nonexistent-bucket/vendor/", mock_s3_client)
        assert exc_info.value.status_code == 404

    def test_get_latest_manifest_access_denied(self, mock_s3_client: MockS3Client):
        """Test error handling when access is denied"""
        mock_s3_client.simulate_error("AccessDenied")

        with pytest.raises(HTTPException) as exc_info:
            get_latest_manifest_file("s3://test-bucket/vendor/", mock_s3_client)
        assert exc_info.value.status_code == 403


class TestManifestAPI:
    """Test manifest API endpoints"""

    def test_get_latest_manifest_success(
        self, client: TestClient, mock_s3_client: MockS3Client
    ):
        """Test successful retrieval of latest manifest"""
        # Setup mock S3 data
        files = [
            {
                "Key": "vendor/manifests/Manifest_2024_01.csv",
                "LastModified": datetime(2024, 1, 1, 12, 0, 0),
                "Size": 1024,
            },
            {
                "Key": "vendor/manifests/Manifest_2024_02.csv",
                "LastModified": datetime(2024, 2, 1, 12, 0, 0),
                "Size": 1536,
            },
        ]
        mock_s3_client.setup_bucket("test-bucket", "vendor/manifests/", files, [])

        # Make API call
        response = client.get(
            "/api/v1/manifest?s3_path=s3://test-bucket/vendor/manifests/"
        )

        # Verify response
        assert response.status_code == 200
        assert (
            response.text == '"s3://test-bucket/vendor/manifests/Manifest_2024_02.csv"'
        )

    def test_get_latest_manifest_no_content(
        self, client: TestClient, mock_s3_client: MockS3Client
    ):
        """Test 204 response when no manifest found"""
        # Setup mock S3 with no manifest files
        files = [
            {
                "Key": "vendor/data.csv",
                "LastModified": datetime(2024, 1, 1, 12, 0, 0),
                "Size": 1024,
            }
        ]
        mock_s3_client.setup_bucket("test-bucket", "vendor/", files, [])

        # Make API call
        response = client.get("/api/v1/manifest?s3_path=s3://test-bucket/vendor/")

        # Verify 204 No Content
        assert response.status_code == 204
        assert response.text == ""

    def test_get_latest_manifest_invalid_path(
        self, client: TestClient
    ):
        """Test 400 error for invalid S3 path"""
        # Make API call with invalid path
        response = client.get("/api/v1/manifest?s3_path=http://bucket/path")

        # Verify 400 Bad Request
        assert response.status_code == 400
        assert "Invalid S3 path format" in response.json()["detail"]

    def test_get_latest_manifest_access_denied(
        self, client: TestClient, mock_s3_client: MockS3Client
    ):
        """Test 403 error when access is denied"""
        mock_s3_client.simulate_error("AccessDenied")

        # Make API call
        response = client.get("/api/v1/manifest?s3_path=s3://test-bucket/vendor/")

        # Verify 403 Forbidden
        assert response.status_code == 403
        assert "Access denied" in response.json()["detail"]

    def test_get_latest_manifest_bucket_not_found(
        self, client: TestClient, mock_s3_client: MockS3Client
    ):
        """Test 404 error when bucket doesn't exist"""
        mock_s3_client.simulate_error("NoSuchBucket")

        # Make API call
        response = client.get(
            "/api/v1/manifest?s3_path=s3://nonexistent-bucket/vendor/"
        )

        # Verify 404 Not Found
        assert response.status_code == 404
        assert "bucket not found" in response.json()["detail"].lower()

    def test_get_latest_manifest_no_credentials(
        self, client: TestClient, mock_s3_client: MockS3Client
    ):
        """Test 401 error when AWS credentials are missing"""
        mock_s3_client.simulate_error("NoCredentialsError")

        # Make API call
        response = client.get("/api/v1/manifest?s3_path=s3://test-bucket/vendor/")

        # Verify 401 Unauthorized
        assert response.status_code == 401
        assert "credentials" in response.json()["detail"].lower()

    def test_get_latest_manifest_missing_parameter(self, client: TestClient):
        """Test 422 error when s3_path parameter is missing"""
        # Make API call without s3_path parameter
        response = client.get("/api/v1/manifest")

        # Verify 422 Unprocessable Entity
        assert response.status_code == 422


class TestManifestUpload:
    """Test manifest upload endpoint"""

    def test_upload_manifest_to_directory(
        self, client: TestClient, mock_s3_client: MockS3Client
    ):
        """Test uploading a manifest to a directory path (ending with /)"""

        # Create a test CSV file
        csv_content = b"Sample_ID,Sample_Name,Project\nS001,Sample1,ProjectA\nS002,Sample2,ProjectB"
        file = io.BytesIO(csv_content)

        # Upload manifest to directory path
        files = {"file": ("test_manifest.csv", file, "text/csv")}
        response = client.post(
            "/api/v1/manifest?s3_path=s3://test-bucket/manifests/",
            files=files
        )

        # Verify successful upload
        assert response.status_code == 201
        data = response.json()
        assert data["status"] == "success"
        assert data["message"] == "Manifest file uploaded successfully"
        assert data["path"] == "s3://test-bucket/manifests/test_manifest.csv"
        assert data["filename"] == "test_manifest.csv"

        # Verify file was uploaded to correct location in mock S3
        assert "test-bucket" in mock_s3_client.uploaded_files
        bucket_files = mock_s3_client.uploaded_files["test-bucket"]
        assert "manifests/test_manifest.csv" in bucket_files
        assert bucket_files["manifests/test_manifest.csv"] == csv_content

    def test_upload_manifest_to_file_path(
        self, client: TestClient, mock_s3_client: MockS3Client
    ):
        """Test uploading a manifest with a specific file path"""

        # Create a test CSV file
        csv_content = b"Sample_ID,Sample_Name\nS001,Sample1"
        file = io.BytesIO(csv_content)

        # Upload manifest with specific filename in path
        files = {"file": ("uploaded.csv", file, "text/csv")}
        response = client.post(
            "/api/v1/manifest?s3_path=s3://test-bucket/manifests/custom_name.csv",
            files=files
        )

        # Verify successful upload
        assert response.status_code == 201
        data = response.json()
        assert data["path"] == "s3://test-bucket/manifests/custom_name.csv"
        assert data["filename"] == "uploaded.csv"

        # Verify file was uploaded with the path-specified name
        assert "manifests/custom_name.csv" in mock_s3_client.uploaded_files["test-bucket"]

    def test_upload_manifest_to_directory_without_trailing_slash(
        self, client: TestClient, mock_s3_client: MockS3Client
    ):
        """Test uploading to a directory path without trailing slash"""

        # Create a test CSV file
        csv_content = b"Sample_ID\nS001"
        file = io.BytesIO(csv_content)

        # Upload manifest to directory path without trailing /
        files = {"file": ("manifest.csv", file, "text/csv")}
        response = client.post(
            "/api/v1/manifest?s3_path=s3://test-bucket/vendor",
            files=files
        )

        # Verify successful upload
        assert response.status_code == 201
        data = response.json()
        assert data["path"] == "s3://test-bucket/vendor/manifest.csv"

        # Verify correct key was used
        assert "vendor/manifest.csv" in mock_s3_client.uploaded_files["test-bucket"]

    def test_upload_manifest_to_root_bucket(
        self, client: TestClient, mock_s3_client: MockS3Client
    ):
        """Test uploading a manifest to the root of a bucket"""

        # Create a test CSV file
        csv_content = b"Sample_ID\nS001"
        file = io.BytesIO(csv_content)

        # Upload to bucket root
        files = {"file": ("root_manifest.csv", file, "text/csv")}
        response = client.post(
            "/api/v1/manifest?s3_path=s3://test-bucket/",
            files=files
        )

        # Verify successful upload
        assert response.status_code == 201
        data = response.json()
        assert data["path"] == "s3://test-bucket/root_manifest.csv"
        assert "root_manifest.csv" in mock_s3_client.uploaded_files["test-bucket"]

    def test_upload_manifest_non_csv_file(
        self, client: TestClient
    ):
        """Test that non-CSV files are rejected"""

        # Create a test text file
        file = io.BytesIO(b"This is not a CSV file")

        # Try to upload non-CSV file
        files = {"file": ("manifest.txt", file, "text/plain")}
        response = client.post(
            "/api/v1/manifest?s3_path=s3://test-bucket/manifests/",
            files=files
        )

        # Verify rejection
        assert response.status_code == 400
        assert "Only CSV files are allowed" in response.json()["detail"]

    def test_upload_manifest_bucket_not_found(
        self, client: TestClient, mock_s3_client: MockS3Client
    ):
        """Test upload fails when bucket doesn't exist"""

        mock_s3_client.simulate_error("NoSuchBucket")

        csv_content = b"Sample_ID\nS001"
        file = io.BytesIO(csv_content)

        files = {"file": ("manifest.csv", file, "text/csv")}
        response = client.post(
            "/api/v1/manifest?s3_path=s3://nonexistent-bucket/manifests/",
            files=files
        )

        # Verify 404 error
        assert response.status_code == 404
        assert "bucket not found" in response.json()["detail"].lower()

    def test_upload_manifest_access_denied(
        self, client: TestClient, mock_s3_client: MockS3Client
    ):
        """Test upload fails when access is denied"""

        mock_s3_client.simulate_error("AccessDenied")

        csv_content = b"Sample_ID\nS001"
        file = io.BytesIO(csv_content)

        files = {"file": ("manifest.csv", file, "text/csv")}
        response = client.post(
            "/api/v1/manifest?s3_path=s3://test-bucket/manifests/",
            files=files
        )

        # Verify 403 error
        assert response.status_code == 403
        assert "Access denied" in response.json()["detail"]

    def test_upload_manifest_no_credentials(
        self, client: TestClient, mock_s3_client: MockS3Client
    ):
        """Test upload fails when AWS credentials are missing"""

        mock_s3_client.simulate_error("NoCredentialsError")

        csv_content = b"Sample_ID\nS001"
        file = io.BytesIO(csv_content)

        files = {"file": ("manifest.csv", file, "text/csv")}
        response = client.post(
            "/api/v1/manifest?s3_path=s3://test-bucket/manifests/",
            files=files
        )

        # Verify 401 error
        assert response.status_code == 401
        assert "credentials" in response.json()["detail"].lower()

    def test_upload_manifest_invalid_s3_path(
        self, client: TestClient
    ):
        """Test upload fails with invalid S3 path format"""

        csv_content = b"Sample_ID\nS001"
        file = io.BytesIO(csv_content)

        files = {"file": ("manifest.csv", file, "text/csv")}
        response = client.post(
            "/api/v1/manifest?s3_path=http://bucket/path",
            files=files
        )

        # Verify 400 error
        assert response.status_code == 400
        assert "Invalid S3 path format" in response.json()["detail"]

    def test_upload_manifest_missing_file(
        self, client: TestClient
    ):
        """Test that request without file fails"""
        response = client.post(
            "/api/v1/manifest?s3_path=s3://test-bucket/manifests/"
        )

        # Verify 422 error (missing required field)
        assert response.status_code == 422


class TestManifestValidation:
    """Test manifest validation endpoint"""

    def test_validate_manifest_valid(
        self, client: TestClient, mock_lambda_client
    ):
        """Test validation endpoint with valid manifest via Lambda"""
        # Configure mock Lambda response for valid manifest
        mock_lambda_client.set_response({
            "success": True,
            "validation_passed": True,
            "messages": {"ManifestVersion": "Validated against manifest version: DTS12.1"},
            "errors": {},
            "warnings": {},
            "manifest_path": "s3://test-bucket/manifest.csv",
            "statusCode": 200
        })

        response = client.post(
            "/api/v1/manifest/validate?s3_path=s3://test-bucket/manifest.csv"
        )

        # Verify successful response
        assert response.status_code == 200

        data = response.json()

        # Verify structure
        assert "valid" in data
        assert "message" in data
        assert "error" in data
        assert "warning" in data

        # Verify valid response
        assert data["valid"] is True
        assert isinstance(data["message"], dict)
        assert isinstance(data["error"], dict)
        assert isinstance(data["warning"], dict)

        # Valid response should have empty errors
        assert len(data["error"]) == 0

        # Should have manifest version message
        assert "ManifestVersion" in data["message"]

    def test_validate_manifest_invalid(
        self, client: TestClient, mock_lambda_client
    ):
        """Test validation endpoint with invalid manifest via Lambda"""
        # Configure mock Lambda response for invalid manifest
        mock_lambda_client.set_response({
            "success": True,
            "validation_passed": False,
            "messages": {
                "ManifestVersion": "Validated against manifest version: DTS12.1",
                "ExtraFields": "See extra fields (info only): ['VHYB', 'VLANE', 'VBARCODE']"
            },
            "errors": {
                "InvalidFilePath": [
                    "Unable to find file s3://example/example_1.clipped.fastq.gz "
                    "described in row 182, check that file exists and is accessible",
                    "Unable to find file s3://example/example_2.clipped.fastq.gz "
                    "described in row 183, check that file exists and is accessible"
                ],
                "MissingRequiredField": [
                    "Row 45 is missing required field 'SAMPLE_ID'",
                    "Row 67 is missing required field 'FILE_PATH'"
                ],
                "InvalidDataFormat": [
                    "Row 92: Invalid date format in field 'RUN_DATE', expected YYYY-MM-DD"
                ]
            },
            "warnings": {
                "DuplicateSample": [
                    "Sample 'ABC-123' appears multiple times in rows 10, 25, 42"
                ]
            },
            "manifest_path": "s3://test-bucket/manifest.csv",
            "statusCode": 422
        })

        response = client.post(
            "/api/v1/manifest/validate?s3_path=s3://test-bucket/manifest.csv"
        )

        # Verify successful response
        assert response.status_code == 200

        data = response.json()

        # Verify structure
        assert "valid" in data
        assert "message" in data
        assert "error" in data
        assert "warning" in data

        # Verify invalid response
        assert data["valid"] is False
        assert isinstance(data["message"], dict)
        assert isinstance(data["error"], dict)
        assert isinstance(data["warning"], dict)

        # Invalid response should have errors
        assert len(data["error"]) > 0

        # Verify expected error categories exist
        assert "InvalidFilePath" in data["error"]
        assert "MissingRequiredField" in data["error"]
        assert "InvalidDataFormat" in data["error"]

        # Verify error messages are lists of strings
        assert isinstance(data["error"]["InvalidFilePath"], list)
        assert len(data["error"]["InvalidFilePath"]) > 0
        assert all(isinstance(msg, str) for msg in data["error"]["InvalidFilePath"])

        # Verify warnings structure
        assert "DuplicateSample" in data["warning"]
        assert isinstance(data["warning"]["DuplicateSample"], list)

        # Verify message has expected keys
        assert "ManifestVersion" in data["message"]
        assert "ExtraFields" in data["message"]

    def test_validate_manifest_missing_s3_path(self, client: TestClient):
        """Test validation endpoint fails without s3_path"""
        response = client.post("/api/v1/manifest/validate")

        # Verify 422 error (missing required parameter)
        assert response.status_code == 422

    def test_validate_manifest_response_structure(
        self, client: TestClient, mock_lambda_client
    ):
        """Test that both valid and invalid responses match expected structure"""
        # Mock Lambda for valid response
        mock_lambda = MagicMock()
        valid_json = (
            b'{"valid": true, "message": {"ManifestVersion": "1.0"}, '
            b'"error": {}, "warning": {}}'
        )
        mock_lambda.invoke.return_value = {
            "Payload": MagicMock(read=lambda: valid_json)
        }

        # Test valid response
        mock_lambda_client.set_response({
            "success": True,
            "validation_passed": True,
            "messages": {"ManifestVersion": "DTS12.1"},
            "errors": {},
            "warnings": {},
            "statusCode": 200
        })
        valid_response = client.post(
            "/api/v1/manifest/validate?s3_path=s3://test-bucket/manifest.csv"
        )
        valid_data = valid_response.json()

        # Mock Lambda for invalid response
        invalid_json = (
            b'{"valid": false, "message": {"ManifestVersion": "1.0"}, '
            b'"error": {"InvalidFilePath": ["Error"]}, "warning": {}}'
        )
        mock_lambda.invoke.return_value = {
            "Payload": MagicMock(read=lambda: invalid_json)
        }

        # Test invalid response
        mock_lambda_client.set_response({
            "success": True,
            "validation_passed": False,
            "messages": {"ManifestVersion": "DTS12.1"},
            "errors": {"SomeError": ["Error message"]},
            "warnings": {"SomeWarning": ["Warning message"]},
            "statusCode": 422
        })
        invalid_response = client.post(
            "/api/v1/manifest/validate?s3_path=s3://test-bucket/manifest.csv"
        )
        invalid_data = invalid_response.json()

        # Both should have the same keys
        assert set(valid_data.keys()) == set(invalid_data.keys())
        assert set(valid_data.keys()) == {"valid", "message", "error", "warning"}

        # Both should have dict types for message, error, warning
        for data in [valid_data, invalid_data]:
            assert isinstance(data["message"], dict)
            assert isinstance(data["error"], dict)
            assert isinstance(data["warning"], dict)
            assert isinstance(data["valid"], bool)

    def test_validate_manifest_lambda_error(
        self, client: TestClient, mock_lambda_client
    ):
        """Test validation endpoint handles Lambda errors"""
        # Configure mock Lambda response for validation request error
        mock_lambda_client.set_response({
            "success": False,
            "error": "manifest_path is required",
            "error_type": "ValidationError",
            "statusCode": 400
        })

        response = client.post(
            "/api/v1/manifest/validate?s3_path=s3://test-bucket/manifest.csv"
        )

        # Verify error response
        assert response.status_code == 400
        assert "manifest_path" in response.json()["detail"]

    def test_validate_manifest_lambda_file_not_found(
        self, client: TestClient, mock_lambda_client
    ):
        """Test validation endpoint handles file not found errors"""
        # Configure mock Lambda response for file not found
        mock_lambda_client.set_response({
            "success": False,
            "error": "Manifest file not found at s3://test-bucket/manifest.csv",
            "error_type": "FileNotFoundError",
            "statusCode": 404
        })

        response = client.post(
            "/api/v1/manifest/validate?s3_path=s3://test-bucket/manifest.csv"
        )

        # Verify error response
        assert response.status_code == 404
        assert "not found" in response.json()["detail"].lower()

    def test_validate_manifest_lambda_service_unavailable(
        self, client: TestClient, mock_lambda_client
    ):
        """Test validation endpoint handles service unavailable errors"""
        # Configure mock Lambda response for service unavailable
        mock_lambda_client.set_response({
            "success": False,
            "error": "Failed to connect to NGS360",
            "error_type": "ServiceUnavailable",
            "statusCode": 503
        })

        response = client.post(
            "/api/v1/manifest/validate?s3_path=s3://test-bucket/manifest.csv"
        )

        # Verify error response
        assert response.status_code == 503
        assert "unavailable" in response.json()["detail"].lower()

    def test_validate_manifest_with_manifest_version(
        self, client: TestClient, mock_lambda_client
    ):
        """Test validation endpoint with manifest_version parameter"""
        mock_lambda_client.set_response({
            "success": True,
            "validation_passed": True,
            "messages": {"ManifestVersion": "DTS12.1"},
            "errors": {},
            "warnings": {},
            "statusCode": 200
        })

        response = client.post(
            "/api/v1/manifest/validate"
            "?s3_path=s3://test-bucket/manifest.csv"
            "&manifest_version=dts12.1"
        )

        assert response.status_code == 200
        data = response.json()
        assert data["valid"] is True

        # Verify manifest_version was passed (uppercased) to Lambda
        last_payload = mock_lambda_client.invocations[-1]["Payload"]
        assert last_payload["manifest_version"] == "DTS12.1"

    def test_validate_manifest_with_files_bucket_and_prefix(
        self, client: TestClient, mock_lambda_client
    ):
        """Test validation endpoint with files_bucket and files_prefix parameters"""
        mock_lambda_client.set_response({
            "success": True,
            "validation_passed": True,
            "messages": {},
            "errors": {},
            "warnings": {},
            "statusCode": 200
        })

        response = client.post(
            "/api/v1/manifest/validate"
            "?s3_path=s3://test-bucket/manifest.csv"
            "&files_bucket=data-bucket"
            "&files_prefix=raw/fastq/"
        )

        assert response.status_code == 200

        # Verify files_bucket and files_prefix were passed to Lambda
        last_payload = mock_lambda_client.invocations[-1]["Payload"]
        assert last_payload["files_bucket"] == "data-bucket"
        assert last_payload["files_prefix"] == "raw/fastq/"

    def test_validate_manifest_files_bucket_defaults_to_s3_path_bucket(
        self, client: TestClient, mock_lambda_client
    ):
        """Test that files_bucket defaults to bucket from s3_path when not provided"""
        mock_lambda_client.set_response({
            "success": True,
            "validation_passed": True,
            "messages": {},
            "errors": {},
            "warnings": {},
            "statusCode": 200
        })

        response = client.post(
            "/api/v1/manifest/validate?s3_path=s3://my-bucket/path/manifest.csv"
        )

        assert response.status_code == 200

        # Verify files_bucket defaulted to bucket from s3_path
        last_payload = mock_lambda_client.invocations[-1]["Payload"]
        assert last_payload["manifest_path"] == "s3://my-bucket/path/manifest.csv"
        assert last_payload["files_bucket"] == "my-bucket"
