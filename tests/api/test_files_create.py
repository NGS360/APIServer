"""Tests for unified file model."""

import pytest
from datetime import datetime, timezone
from api.files.models import (
    File,
    FileEntityType,
    FileCreate,
    EntityInput,
    SampleInput,
)


class TestFileURIGeneration:
    """Test file URI generation logic."""

    def test_generate_uri_no_subdirectory(self):
        """Test URI generation without subdirectory."""
        uri = File.generate_uri(
            base_path="s3://bucket",
            entity_type="project",
            entity_id="P-20260109-0001",
            filename="file.txt"
        )
        assert uri == "s3://bucket/project/P-20260109-0001/file.txt"

    def test_generate_uri_with_subdirectory(self):
        """Test URI generation with subdirectory."""
        uri = File.generate_uri(
            base_path="s3://bucket",
            entity_type="project",
            entity_id="P-20260109-0001",
            filename="file.txt",
            relative_path="raw_data/sample1"
        )
        assert uri == "s3://bucket/project/P-20260109-0001/raw_data/sample1/file.txt"

    def test_generate_uri_with_trailing_slash(self):
        """Test that trailing slashes are handled in base_path."""
        uri = File.generate_uri(
            base_path="s3://bucket/",
            entity_type="project",
            entity_id="P-20260109-0001",
            filename="file.txt"
        )
        assert uri == "s3://bucket/project/P-20260109-0001/file.txt"

    def test_generate_uri_with_trailing_slash_in_relative_path(self):
        """Test that trailing slashes are handled in relative_path."""
        uri = File.generate_uri(
            base_path="s3://bucket",
            entity_type="project",
            entity_id="P-20260109-0001",
            filename="file.txt",
            relative_path="raw_data/"
        )
        assert uri == "s3://bucket/project/P-20260109-0001/raw_data/file.txt"


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


class TestFileChecksumCalculation:
    """Test file checksum calculation."""

    def test_calculate_sha256(self):
        """Test SHA256 checksum calculation."""
        content = b"test content"
        checksum = File.calculate_checksum(content, "sha256")
        assert len(checksum) == 64  # SHA256 produces 64 hex chars
        assert checksum == "6ae8a75555209fd6c44157c0aed8016e763ff435a19cf186f76863140143ff72"

    def test_calculate_md5(self):
        """Test MD5 checksum calculation."""
        content = b"test content"
        checksum = File.calculate_checksum(content, "md5")
        assert len(checksum) == 32  # MD5 produces 32 hex chars


class TestFileMimeType:
    """Test MIME type detection."""

    def test_get_mime_type_txt(self):
        """Test MIME type for text file."""
        mime_type = File.get_mime_type("file.txt")
        assert mime_type == "text/plain"

    def test_get_mime_type_json(self):
        """Test MIME type for JSON file."""
        mime_type = File.get_mime_type("data.json")
        assert mime_type == "application/json"

    def test_get_mime_type_fastq(self):
        """Test MIME type for FASTQ file (unknown extension)."""
        mime_type = File.get_mime_type("sample.fastq")
        assert mime_type == "application/octet-stream"


class TestFileEntityType:
    """Test FileEntityType constants."""

    def test_entity_types_exist(self):
        """Test that all entity types are defined."""
        assert FileEntityType.PROJECT == "PROJECT"
        assert FileEntityType.SAMPLE == "SAMPLE"
        assert FileEntityType.QCRECORD == "QCRECORD"


class TestFileCreateSchema:
    """Test FileCreate schema validation."""

    def test_minimal_file_create(self):
        """Test creating FileCreate with minimal fields."""
        file_create = FileCreate(
            uri="s3://bucket/file.txt",
        )
        assert file_create.uri == "s3://bucket/file.txt"
        assert file_create.size is None
        assert file_create.hashes is None
        assert file_create.tags is None
        assert file_create.samples is None
        assert file_create.entities is None

    def test_full_file_create(self):
        """Test creating FileCreate with all fields."""
        file_create = FileCreate(
            uri="s3://bucket/file.txt",
            size=1024,
            created_on=datetime(2024, 1, 15, 12, 0, 0, tzinfo=timezone.utc),
            hashes={"sha256": "abc123", "md5": "def456"},
            tags={"type": "raw_data", "format": "fastq"},
            project_id="P-123",
            samples=[SampleInput(sample_name="sample1", role="tumor")],
            entities=[EntityInput(entity_type="PROJECT", entity_id="P-123")],
        )
        assert file_create.uri == "s3://bucket/file.txt"
        assert file_create.size == 1024
        assert file_create.created_on == datetime(2024, 1, 15, 12, 0, 0, tzinfo=timezone.utc)
        assert file_create.hashes["sha256"] == "abc123"
        assert file_create.tags["type"] == "raw_data"
        assert len(file_create.samples) == 1
        assert len(file_create.entities) == 1


class TestFileFilenameProperty:
    """Test File.filename property derivation from URI."""

    def test_filename_from_s3_uri(self):
        """Test filename extraction from S3 URI."""
        file = File(
            uri="s3://bucket/path/to/file.txt",
        )
        assert file.filename == "file.txt"

    def test_filename_from_file_uri(self):
        """Test filename extraction from file URI."""
        file = File(
            uri="file:///data/project/results.csv",
        )
        assert file.filename == "results.csv"

    def test_filename_from_http_uri(self):
        """Test filename extraction from HTTP URI."""
        file = File(
            uri="https://example.com/downloads/data.zip",
        )
        assert file.filename == "data.zip"
