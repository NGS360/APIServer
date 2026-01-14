"""Tests for file creation with subdirectory support."""

import pytest
from fastapi import HTTPException
from api.files.models import File, EntityType, FileCreate
from api.files.services import create_file


class TestFilePathGeneration:
    """Test file path generation logic."""

    def test_generate_path_no_subdirectory(self):
        """Test path generation without subdirectory."""
        path = File.generate_file_path(
            EntityType.PROJECT,
            "P-20260109-0001",
            "abc123_file.txt"
        )
        assert path == "project/P-20260109-0001/abc123_file.txt"

    def test_generate_path_with_subdirectory(self):
        """Test path generation with subdirectory."""
        path = File.generate_file_path(
            EntityType.PROJECT,
            "P-20260109-0001",
            "abc123_file.txt",
            relative_path="raw_data/sample1"
        )
        assert path == "project/P-20260109-0001/raw_data/sample1/abc123_file.txt"

    def test_generate_path_with_trailing_slash(self):
        """Test that trailing slashes are handled."""
        path = File.generate_file_path(
            EntityType.PROJECT,
            "P-20260109-0001",
            "abc123_file.txt",
            relative_path="raw_data/"
        )
        assert path == "project/P-20260109-0001/raw_data/abc123_file.txt"


class TestRelativePathValidation:
    """Test relative path validation."""

    def test_validate_valid_path(self):
        """Test that valid paths pass validation."""
        path = File.validate_relative_path("raw_data/sample1")
        assert path == "raw_data/sample1"

    def test_validate_none(self):
        """Test that None is handled."""
        path = File.validate_relative_path(None)
        assert path is None

    def test_validate_empty_string(self):
        """Test that empty string returns None."""
        path = File.validate_relative_path("")
        assert path is None

    def test_validate_path_traversal(self):
        """Test that path traversal is blocked."""
        with pytest.raises(ValueError, match="Path traversal"):
            File.validate_relative_path("../etc/passwd")

    def test_validate_absolute_path(self):
        """Test that absolute paths are blocked."""
        with pytest.raises(ValueError, match="Absolute paths"):
            File.validate_relative_path("/etc/passwd")

    def test_validate_double_slash(self):
        """Test that double slashes are blocked."""
        with pytest.raises(ValueError, match="Double slashes"):
            File.validate_relative_path("raw_data//sample1")


class TestFileCreation:
    """Test file creation with new path structure."""

    def test_create_file_at_root(self, session, mock_s3_client, test_project):
        """Test creating file at entity root."""
        file_create = FileCreate(
            filename="test.txt",
            entity_type=EntityType.PROJECT,
            entity_id=test_project.project_id,
            relative_path=None,
        )

        file_record = create_file(
            session, mock_s3_client, file_create, file_content=b"test content"
        )

        assert file_record.relative_path is None
        assert file_record.file_path.endswith(f"{test_project.project_id}/{file_record.file_id}_test.txt")

    def test_create_file_in_subdirectory(self, session, mock_s3_client, test_project):
        """Test creating file in subdirectory."""
        file_create = FileCreate(
            filename="test.fastq",
            entity_type=EntityType.PROJECT,
            entity_id=test_project.project_id,
            relative_path="raw_data/sample1",
        )

        file_record = create_file(
            session, mock_s3_client, file_create, file_content=b"ATCG"
        )

        assert file_record.relative_path == "raw_data/sample1"
        assert "raw_data/sample1" in file_record.file_path

    def test_create_file_invalid_entity(self, session, mock_s3_client):
        """Test that creating file for non-existent entity fails."""
        file_create = FileCreate(
            filename="test.txt",
            entity_type=EntityType.PROJECT,
            entity_id="P-99999999-9999",
            relative_path=None,
        )

        with pytest.raises(HTTPException, match="Project not found"):
            create_file(session, mock_s3_client, file_create, file_content=b"test")
