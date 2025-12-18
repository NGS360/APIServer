"""
Test /manifest endpoint
"""

from datetime import datetime

from fastapi.testclient import TestClient

from tests.conftest import MockS3Client


class TestManifestServices:
    """Test manifest service functions"""

    def test_parse_s3_path(self):
        """Test S3 path parsing in manifest service"""
        from api.manifest.services import _parse_s3_path

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
        from api.manifest.services import get_latest_manifest_file

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
        from api.manifest.services import get_latest_manifest_file

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
        from api.manifest.services import get_latest_manifest_file

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
        from api.manifest.services import get_latest_manifest_file

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
        from api.manifest.services import get_latest_manifest_file

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
        from api.manifest.services import get_latest_manifest_file

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
        from api.manifest.services import get_latest_manifest_file

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
        from api.manifest.services import get_latest_manifest_file

        # Empty bucket
        mock_s3_client.setup_bucket("test-bucket", "vendor/", [], [])

        result = get_latest_manifest_file("s3://test-bucket/vendor/", mock_s3_client)

        assert result is None

    def test_get_latest_manifest_invalid_path(self, mock_s3_client: MockS3Client):
        """Test error handling for invalid S3 path"""
        from api.manifest.services import get_latest_manifest_file
        from fastapi import HTTPException
        import pytest

        # Invalid S3 paths
        invalid_paths = ["http://bucket/path", "s3://", "s3:///bucket"]

        for path in invalid_paths:
            with pytest.raises(HTTPException) as exc_info:
                get_latest_manifest_file(path, mock_s3_client)
            assert exc_info.value.status_code == 400

    def test_get_latest_manifest_no_credentials(self, mock_s3_client: MockS3Client):
        """Test error handling when AWS credentials are missing"""
        from api.manifest.services import get_latest_manifest_file
        from fastapi import HTTPException
        import pytest

        mock_s3_client.simulate_error("NoCredentialsError")

        with pytest.raises(HTTPException) as exc_info:
            get_latest_manifest_file("s3://test-bucket/vendor/", mock_s3_client)
        assert exc_info.value.status_code == 401

    def test_get_latest_manifest_bucket_not_found(self, mock_s3_client: MockS3Client):
        """Test error handling when bucket doesn't exist"""
        from api.manifest.services import get_latest_manifest_file
        from fastapi import HTTPException
        import pytest

        mock_s3_client.simulate_error("NoSuchBucket")

        with pytest.raises(HTTPException) as exc_info:
            get_latest_manifest_file("s3://nonexistent-bucket/vendor/", mock_s3_client)
        assert exc_info.value.status_code == 404

    def test_get_latest_manifest_access_denied(self, mock_s3_client: MockS3Client):
        """Test error handling when access is denied"""
        from api.manifest.services import get_latest_manifest_file
        from fastapi import HTTPException
        import pytest

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
        self, client: TestClient, mock_s3_client: MockS3Client
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
        import io

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
        assert "manifests/test_manifest.csv" in mock_s3_client.uploaded_files["test-bucket"]
        assert mock_s3_client.uploaded_files["test-bucket"]["manifests/test_manifest.csv"] == csv_content

    def test_upload_manifest_to_file_path(
        self, client: TestClient, mock_s3_client: MockS3Client
    ):
        """Test uploading a manifest with a specific file path"""
        import io

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
        import io

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
        import io

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
        self, client: TestClient, mock_s3_client: MockS3Client
    ):
        """Test that non-CSV files are rejected"""
        import io

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
        import io

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
        import io

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
        import io

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
        self, client: TestClient, mock_s3_client: MockS3Client
    ):
        """Test upload fails with invalid S3 path format"""
        import io

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
        self, client: TestClient, mock_s3_client: MockS3Client
    ):
        """Test that request without file fails"""
        response = client.post(
            "/api/v1/manifest?s3_path=s3://test-bucket/manifests/"
        )

        # Verify 422 error (missing required field)
        assert response.status_code == 422
