"""
Test /files endpoint
"""

from datetime import datetime
from io import BytesIO

from fastapi.testclient import TestClient

from tests.conftest import MockS3Client


class TestFileServices:
    """Test file services functions"""

    def test_parse_s3_path(self):
        """Test S3 path parsing"""
        from api.files.services import _parse_s3_path

        # Valid paths
        assert _parse_s3_path("s3://my-bucket") == ("my-bucket", "")
        assert _parse_s3_path("s3://my-bucket/") == ("my-bucket", "")
        assert _parse_s3_path("s3://my-bucket/prefix") == ("my-bucket", "prefix")
        assert _parse_s3_path("s3://my-bucket/prefix/") == ("my-bucket", "prefix/")
        assert _parse_s3_path("s3://my-bucket/prefix/subprefix/file.txt") == (
            "my-bucket",
            "prefix/subprefix/file.txt",
        )

        # Invalid paths
        invalid_paths = [
            "http://my-bucket",
            "s3:/my-bucket",
            "s3//my-bucket",
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

    def test__list_local_storage(self, tmp_path):
        """Test listing local storage directory"""
        # Setup test directory structure
        (tmp_path / "subfolder1").mkdir()
        (tmp_path / "subfolder2").mkdir()
        (tmp_path / "file1.txt").write_text("This is file 1")
        (tmp_path / "file2.txt").write_text("This is file 2")
        (tmp_path / "zebra.txt").write_text("This is zebra")

        from api.files.services import _list_local_storage

        result = _list_local_storage(str(tmp_path))

        # Verify structure
        assert "folders" in result.model_dump()
        assert "files" in result.model_dump()
        assert isinstance(result.folders, list)
        assert isinstance(result.files, list)

        # Verify we have folders and files
        assert len(result.folders) == 2
        assert len(result.files) == 3

        # Verify folder names
        folder_names = [f.name for f in result.folders]
        assert "subfolder1" in folder_names
        assert "subfolder2" in folder_names

        # Verify file names
        file_names = [f.name for f in result.files]
        assert "file1.txt" in file_names
        assert "file2.txt" in file_names
        assert "zebra.txt" in file_names

        # Verify files have size and date
        for file in result.files:
            assert file.size > 0
            assert isinstance(file.date, str)
            assert len(file.date) > 0  # Date string should not be empty


class TestFileBrowserAPI:
    """Test file browser API endpoints"""

    def test_list_s3(self, client: TestClient, mock_s3_client: MockS3Client):
        """Test S3 browsing with proper mocking"""
        # Setup mock S3 data
        files = [
            {
                "Key": "a_folder/file_0.txt",
                "LastModified": datetime(2024, 1, 1, 12, 0, 0),
                "Size": 100,
            },
            {
                "Key": "a_folder/file_1.txt",
                "LastModified": datetime(2024, 1, 2, 12, 0, 0),
                "Size": 101,
            },
            {
                "Key": "a_folder/file_2.txt",
                "LastModified": datetime(2024, 1, 3, 12, 0, 0),
                "Size": 102,
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

    def test_list_s3_files_only(self, client: TestClient, mock_s3_client: MockS3Client):
        """Test S3 bucket with only files, no folders"""
        files = [
            {
                "Key": "file1.txt",
                "LastModified": datetime(2024, 1, 1, 12, 0, 0),
                "Size": 100,
            },
            {
                "Key": "file2.txt",
                "LastModified": datetime(2024, 1, 2, 12, 0, 0),
                "Size": 200,
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
                "Size": 100,
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

    def test_list_s3_sorting(self, client: TestClient, mock_s3_client: MockS3Client):
        """Test that files and folders are sorted alphabetically"""
        files = [
            {
                "Key": "prefix/zebra.txt",
                "LastModified": datetime(2024, 1, 1, 12, 0, 0),
                "Size": 100,
            },
            {
                "Key": "prefix/apple.txt",
                "LastModified": datetime(2024, 1, 2, 12, 0, 0),
                "Size": 200,
            },
            {
                "Key": "prefix/middle.txt",
                "LastModified": datetime(2024, 1, 3, 12, 0, 0),
                "Size": 300,
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
        """Test local storage browsing via API"""
        import shutil
        from pathlib import Path

        # Create storage directory structure in workspace
        storage_dir = Path("storage/test_folder")
        storage_dir.mkdir(parents=True, exist_ok=True)

        try:
            # Create test files and folders
            (storage_dir / "subfolder1").mkdir(exist_ok=True)
            (storage_dir / "subfolder2").mkdir(exist_ok=True)
            (storage_dir / "file1.txt").write_text("Test content 1")
            (storage_dir / "file2.txt").write_text("Test content 2")

            # Call API endpoint
            response = client.get("/api/v1/files/list?uri=test_folder")

            assert response.status_code == 200
            data = response.json()

            # Verify structure
            assert "folders" in data
            assert "files" in data
            assert isinstance(data["folders"], list)
            assert isinstance(data["files"], list)

            # Verify we have folders and files
            assert len(data["folders"]) == 2
            assert len(data["files"]) == 2

            # Verify folder names
            folder_names = [f["name"] for f in data["folders"]]
            assert "subfolder1" in folder_names
            assert "subfolder2" in folder_names

            # Verify file names
            file_names = [f["name"] for f in data["files"]]
            assert "file1.txt" in file_names
            assert "file2.txt" in file_names

            # Verify files have size and date
            for file in data["files"]:
                assert file["size"] > 0
                assert isinstance(file["date"], str)
                assert len(file["date"]) > 0
        finally:
            # Cleanup: remove test storage directory
            if Path("storage").exists():
                shutil.rmtree("storage")

    def test_upload_file_to_s3(self, client: TestClient, mock_s3_client: MockS3Client):
        """Test uploading a file to S3"""
        file_content = b"Test file content for upload"
        uri = "s3://test-bucket/uploads/test-file.txt"
        
        response = client.post(
            "/api/v1/files/upload",
            data={"uri": uri},
            files={"file": ("test-file.txt", BytesIO(file_content), "text/plain")}
        )
        
        assert response.status_code == 201
        
        # Verify the file was uploaded to mock S3
        assert "test-bucket" in mock_s3_client.uploaded_files
        assert "uploads/test-file.txt" in mock_s3_client.uploaded_files["test-bucket"]
        assert mock_s3_client.uploaded_files["test-bucket"]["uploads/test-file.txt"] == file_content

    def test_upload_file_to_local_storage(self, client: TestClient):
        """Test uploading a file to local storage"""
        import shutil
        from pathlib import Path
        
        file_content = b"Test file content for local upload"
        uri = "test_uploads/test-file.txt"
        
        try:
            response = client.post(
                "/api/v1/files/upload",
                data={"uri": uri},
                files={"file": ("test-file.txt", BytesIO(file_content), "text/plain")}
            )
            
            assert response.status_code == 201
            
            # Verify the file was created
            uploaded_file = Path("storage") / uri
            assert uploaded_file.exists()
            assert uploaded_file.read_bytes() == file_content
        finally:
            # Cleanup
            if Path("storage").exists():
                shutil.rmtree("storage")

    def test_upload_file_s3_bucket_not_found(self, client: TestClient, mock_s3_client: MockS3Client):
        """Test upload fails when S3 bucket doesn't exist"""
        mock_s3_client.simulate_error("NoSuchBucket")
        
        file_content = b"Test content"
        uri = "s3://nonexistent-bucket/file.txt"
        
        response = client.post(
            "/api/v1/files/upload",
            data={"uri": uri},
            files={"file": ("test.txt", BytesIO(file_content), "text/plain")}
        )
        
        assert response.status_code == 404
        assert "bucket not found" in response.json()["detail"].lower()

    def test_upload_file_s3_access_denied(self, client: TestClient, mock_s3_client: MockS3Client):
        """Test upload fails when access is denied"""
        mock_s3_client.simulate_error("AccessDenied")
        
        file_content = b"Test content"
        uri = "s3://restricted-bucket/file.txt"
        
        response = client.post(
            "/api/v1/files/upload",
            data={"uri": uri},
            files={"file": ("test.txt", BytesIO(file_content), "text/plain")}
        )
        
        assert response.status_code == 403
        assert "access denied" in response.json()["detail"].lower()

    def test_upload_file_s3_no_credentials(self, client: TestClient, mock_s3_client: MockS3Client):
        """Test upload fails when AWS credentials are missing"""
        mock_s3_client.simulate_error("NoCredentialsError")
        
        file_content = b"Test content"
        uri = "s3://test-bucket/file.txt"
        
        response = client.post(
            "/api/v1/files/upload",
            data={"uri": uri},
            files={"file": ("test.txt", BytesIO(file_content), "text/plain")}
        )
        
        assert response.status_code == 401
        assert "credentials" in response.json()["detail"].lower()
