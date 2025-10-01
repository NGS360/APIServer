"""
Test /files endpoint
"""
from datetime import datetime
from fastapi.testclient import TestClient

from tests.conftest import MockS3Client


class TestFileBrowserAPI:
    """Test file browser API endpoints"""

    def test_list_s3(self, client: TestClient, mock_s3_client: MockS3Client):
        """Test S3 browsing with proper mocking"""
        # Setup mock S3 data
        files = [
            {
                "Key": "a_folder/file_0.txt",
                "LastModified": datetime(2024, 1, 1, 12, 0, 0),
                "Size": 100
            },
            {
                "Key": "a_folder/file_1.txt",
                "LastModified": datetime(2024, 1, 2, 12, 0, 0),
                "Size": 101
            },
            {
                "Key": "a_folder/file_2.txt",
                "LastModified": datetime(2024, 1, 3, 12, 0, 0),
                "Size": 102
            },
        ]
        folders = ["a_folder/folder_0/", "a_folder/folder_1/"]

        mock_s3_client.setup_bucket("test-bucket", "a_folder/", files, folders)

        # Make API call
        response = client.get("/api/v1/files/list?uri=s3://test-bucket/a_folder/")

        # Verify response
        assert response.status_code == 200
        data = response.json()

        # Verify structure
        assert "folders" in data
        assert "files" in data
        assert isinstance(data["folders"], list)
        assert isinstance(data["files"], list)

        # Verify counts
        assert len(data["folders"]) == 2
        assert len(data["files"]) == 3

        # Verify folder names
        folder_names = [f["name"] for f in data["folders"]]
        assert "folder_0" in folder_names
        assert "folder_1" in folder_names

        # Verify file details
        file_names = [f["name"] for f in data["files"]]
        assert "file_0.txt" in file_names
        assert "file_1.txt" in file_names
        assert "file_2.txt" in file_names

        # Verify file sizes
        file_sizes = {f["name"]: f["size"] for f in data["files"]}
        assert file_sizes["file_0.txt"] == 100
        assert file_sizes["file_1.txt"] == 101
        assert file_sizes["file_2.txt"] == 102

    def test_list_s3_empty_bucket(
        self, client: TestClient, mock_s3_client: MockS3Client
    ):
        """Test listing empty S3 bucket"""
        mock_s3_client.setup_bucket("test-bucket", "", [], [])

        response = client.get("/api/v1/files/list?uri=s3://test-bucket/")

        assert response.status_code == 200
        data = response.json()
        assert len(data["folders"]) == 0
        assert len(data["files"]) == 0

    def test_list_s3_files_only(
        self, client: TestClient, mock_s3_client: MockS3Client
    ):
        """Test S3 bucket with only files, no folders"""
        files = [
            {
                "Key": "file1.txt",
                "LastModified": datetime(2024, 1, 1, 12, 0, 0),
                "Size": 100
            },
            {
                "Key": "file2.txt",
                "LastModified": datetime(2024, 1, 2, 12, 0, 0),
                "Size": 200
            },
        ]
        mock_s3_client.setup_bucket("test-bucket", "", files, [])

        response = client.get("/api/v1/files/list?uri=s3://test-bucket/")

        assert response.status_code == 200
        data = response.json()
        assert len(data["folders"]) == 0
        assert len(data["files"]) == 2

    def test_list_s3_folders_only(
        self, client: TestClient, mock_s3_client: MockS3Client
    ):
        """Test S3 bucket with only folders, no files"""
        folders = ["folder1/", "folder2/"]
        mock_s3_client.setup_bucket("test-bucket", "", [], folders)

        response = client.get("/api/v1/files/list?uri=s3://test-bucket/")

        assert response.status_code == 200
        data = response.json()
        assert len(data["folders"]) == 2
        assert len(data["files"]) == 0

    def test_list_s3_bucket_not_found(
        self, client: TestClient, mock_s3_client: MockS3Client
    ):
        """Test error when S3 bucket doesn't exist"""
        mock_s3_client.simulate_error("NoSuchBucket")

        response = client.get("/api/v1/files/list?uri=s3://nonexistent-bucket/")

        assert response.status_code == 404
        assert "not found" in response.json()["detail"].lower()

    def test_list_s3_access_denied(
        self, client: TestClient, mock_s3_client: MockS3Client
    ):
        """Test error when access is denied to S3 bucket"""
        mock_s3_client.simulate_error("AccessDenied")

        response = client.get("/api/v1/files/list?uri=s3://test-bucket/")

        assert response.status_code == 403
        assert "access denied" in response.json()["detail"].lower()

    def test_list_s3_no_credentials(
        self, client: TestClient, mock_s3_client: MockS3Client
    ):
        """Test error when AWS credentials are not configured"""
        mock_s3_client.simulate_error("NoCredentialsError")

        response = client.get("/api/v1/files/list?uri=s3://test-bucket/")

        assert response.status_code == 401
        assert "credentials" in response.json()["detail"].lower()

    def test_list_s3_nested_prefix(
        self, client: TestClient, mock_s3_client: MockS3Client
    ):
        """Test listing files in nested S3 prefix"""
        files = [
            {
                "Key": "a/b/c/file.txt",
                "LastModified": datetime(2024, 1, 1, 12, 0, 0),
                "Size": 100
            },
        ]
        folders = ["a/b/c/subfolder/"]
        mock_s3_client.setup_bucket("test-bucket", "a/b/c/", files, folders)

        response = client.get("/api/v1/files/list?uri=s3://test-bucket/a/b/c/")

        assert response.status_code == 200
        data = response.json()
        assert len(data["files"]) == 1
        assert data["files"][0]["name"] == "file.txt"
        assert len(data["folders"]) == 1
        assert data["folders"][0]["name"] == "subfolder"

    def test_list_s3_sorting(
        self, client: TestClient, mock_s3_client: MockS3Client
    ):
        """Test that files and folders are sorted alphabetically"""
        files = [
            {
                "Key": "prefix/zebra.txt",
                "LastModified": datetime(2024, 1, 1, 12, 0, 0),
                "Size": 100
            },
            {
                "Key": "prefix/apple.txt",
                "LastModified": datetime(2024, 1, 2, 12, 0, 0),
                "Size": 200
            },
            {
                "Key": "prefix/middle.txt",
                "LastModified": datetime(2024, 1, 3, 12, 0, 0),
                "Size": 300
            },
        ]
        folders = ["prefix/zoo/", "prefix/aardvark/", "prefix/middle/"]
        mock_s3_client.setup_bucket("test-bucket", "prefix/", files, folders)

        response = client.get("/api/v1/files/list?uri=s3://test-bucket/prefix/")

        assert response.status_code == 200
        data = response.json()

        # Verify alphabetical sorting
        file_names = [f["name"] for f in data["files"]]
        assert file_names == ["apple.txt", "middle.txt", "zebra.txt"]

        folder_names = [f["name"] for f in data["folders"]]
        assert folder_names == ["aardvark", "middle", "zoo"]

    def test_list_local_storage(self, client: TestClient):
        """Test listing local storage directory"""
        # Use the test fixtures directory
        response = client.get("/api/v1/files/list?uri=tests/fixtures/test_storage")

        assert response.status_code == 200
        data = response.json()

        # Verify structure
        assert "folders" in data
        assert "files" in data
        assert isinstance(data["folders"], list)
        assert isinstance(data["files"], list)

        # Verify we have folders and files
        assert len(data["folders"]) == 2  # subfolder1, subfolder2
        assert len(data["files"]) == 3  # file1.txt, file2.txt, zebra.txt

        # Verify folder names
        folder_names = [f["name"] for f in data["folders"]]
        assert "subfolder1" in folder_names
        assert "subfolder2" in folder_names

        # Verify file names
        file_names = [f["name"] for f in data["files"]]
        assert "file1.txt" in file_names
        assert "file2.txt" in file_names
        assert "zebra.txt" in file_names

        # Verify files have size and date
        for file in data["files"]:
            assert "size" in file
            assert "date" in file
            assert file["size"] > 0

    def test_list_local_storage_with_leading_slash(self, client: TestClient):
        """Test listing local storage with leading slash in path"""
        response = client.get("/api/v1/files/list?uri=/tests/fixtures/test_storage")

        assert response.status_code == 200
        data = response.json()
        assert len(data["folders"]) == 2
        assert len(data["files"]) == 3

    def test_list_local_storage_sorting(self, client: TestClient):
        """Test that local storage files and folders are sorted alphabetically"""
        response = client.get("/api/v1/files/list?uri=tests/fixtures/test_storage")

        assert response.status_code == 200
        data = response.json()

        # Verify alphabetical sorting (case-insensitive)
        file_names = [f["name"] for f in data["files"]]
        assert file_names == ["file1.txt", "file2.txt", "zebra.txt"]

        folder_names = [f["name"] for f in data["folders"]]
        assert folder_names == ["subfolder1", "subfolder2"]

    def test_list_local_storage_nonexistent_directory(self, client: TestClient):
        """Test error when directory doesn't exist"""
        response = client.get(
            "/api/v1/files/list?uri=tests/fixtures/nonexistent_directory"
        )

        assert response.status_code == 404
        assert "not found" in response.json()["detail"].lower()

    def test_list_local_storage_file_not_directory(self, client: TestClient):
        """Test error when path points to a file instead of directory"""
        response = client.get(
            "/api/v1/files/list?uri=tests/fixtures/test_storage/file1.txt"
        )

        assert response.status_code == 400
        assert "not a directory" in response.json()["detail"].lower()

    def test_list_local_storage_empty_directory(self, client: TestClient):
        """Test listing an empty directory"""
        # Create empty directory for test
        import os
        empty_dir = "tests/fixtures/test_storage/empty_dir"
        os.makedirs(empty_dir, exist_ok=True)

        try:
            response = client.get(f"/api/v1/files/list?uri={empty_dir}")

            assert response.status_code == 200
            data = response.json()
            assert len(data["folders"]) == 0
            assert len(data["files"]) == 0
        finally:
            # Cleanup
            if os.path.exists(empty_dir):
                os.rmdir(empty_dir)
