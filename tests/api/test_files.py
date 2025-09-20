"""
Test /files endpoint
"""

import tempfile
import shutil
from pathlib import Path
from datetime import datetime

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session

from api.files.models import (
    FileCreate,
    FileUpdate,
    FileType,
    EntityType,
    StorageBackend,
)
from api.files.services import (
    create_file,
    get_file,
    update_file,
    delete_file,
    list_files,
    get_file_content,
    list_files_for_entity,
    get_file_count_for_entity,
    generate_file_id,
    generate_file_path,
    calculate_file_checksum,
    get_mime_type,
)


class TestFileModels:
    """Test file model functionality"""

    def test_file_type_enum(self):
        """Test FileType enum values"""
        assert FileType.FASTQ == "fastq"
        assert FileType.BAM == "bam"
        assert FileType.VCF == "vcf"
        assert FileType.SAMPLESHEET == "samplesheet"
        assert FileType.METRICS == "metrics"
        assert FileType.REPORT == "report"
        assert FileType.LOG == "log"
        assert FileType.IMAGE == "image"
        assert FileType.DOCUMENT == "document"
        assert FileType.OTHER == "other"

    def test_entity_type_enum(self):
        """Test EntityType enum values"""
        assert EntityType.PROJECT == "project"
        assert EntityType.RUN == "run"

    def test_storage_backend_enum(self):
        """Test StorageBackend enum values"""
        assert StorageBackend.LOCAL == "local"
        assert StorageBackend.S3 == "s3"
        assert StorageBackend.AZURE == "azure"
        assert StorageBackend.GCS == "gcs"

    def test_file_create_model(self):
        """Test FileCreate model validation"""
        file_create = FileCreate(
            filename="test.txt",
            description="Test file",
            file_type=FileType.DOCUMENT,
            entity_type=EntityType.PROJECT,
            entity_id="PROJ001",
            is_public=True,
            created_by="testuser"
        )

        assert file_create.filename == "test.txt"
        assert file_create.description == "Test file"
        assert file_create.file_type == FileType.DOCUMENT
        assert file_create.entity_type == EntityType.PROJECT
        assert file_create.entity_id == "PROJ001"
        assert file_create.is_public is True
        assert file_create.created_by == "testuser"

    def test_file_update_model(self):
        """Test FileUpdate model validation"""
        file_update = FileUpdate(
            filename="updated.txt",
            description="Updated description",
            is_public=False
        )

        assert file_update.filename == "updated.txt"
        assert file_update.description == "Updated description"
        assert file_update.is_public is False


class TestFileServices:
    """Test file service functions"""

    @pytest.fixture
    def temp_storage(self):
        """Create temporary storage directory"""
        temp_dir = tempfile.mkdtemp()
        yield temp_dir
        shutil.rmtree(temp_dir)

    def test_generate_file_id(self):
        """Test file ID generation"""
        file_id = generate_file_id()
        assert len(file_id) == 12
        assert file_id.isalnum()

        # Test uniqueness
        file_id2 = generate_file_id()
        assert file_id != file_id2

    def test_generate_file_path(self):
        """Test file path generation"""
        path = generate_file_path(
            EntityType.PROJECT,
            "PROJ001",
            FileType.FASTQ,
            "sample.fastq"
        )

        # Should contain entity type, entity id, file type, year, month, filename
        path_parts = path.split("/")
        assert len(path_parts) == 6
        assert path_parts[0] == "project"
        assert path_parts[1] == "PROJ001"
        assert path_parts[2] == "fastq"
        assert path_parts[5] == "sample.fastq"

        # Year and month should be current
        now = datetime.utcnow()
        assert path_parts[3] == now.strftime("%Y")
        assert path_parts[4] == now.strftime("%m")

    def test_calculate_file_checksum(self):
        """Test file checksum calculation"""
        content = b"Hello, World!"
        checksum = calculate_file_checksum(content)

        # Should be SHA-256 hash
        assert len(checksum) == 64
        assert checksum == "dffd6021bb2bd5b0af676290809ec3a53191dd81c7f70a4b28688a362182986f"

    def test_get_mime_type(self):
        """Test MIME type detection"""
        assert get_mime_type("test.txt") == "text/plain"
        assert get_mime_type("test.pdf") == "application/pdf"
        assert get_mime_type("test.jpg") == "image/jpeg"
        assert get_mime_type("test.fastq") == "application/octet-stream"  # Unknown extension

    def test_create_file_without_content(self, session: Session, temp_storage):
        """Test creating file record without content"""
        file_create = FileCreate(
            filename="test.txt",
            description="Test file",
            file_type=FileType.DOCUMENT,
            entity_type=EntityType.PROJECT,
            entity_id="PROJ001",
            created_by="testuser"
        )

        file_record = create_file(session, file_create, storage_root=temp_storage)

        assert file_record.filename == "test.txt"
        assert file_record.description == "Test file"
        assert file_record.file_type == FileType.DOCUMENT
        assert file_record.entity_type == EntityType.PROJECT
        assert file_record.entity_id == "PROJ001"
        assert file_record.created_by == "testuser"
        assert file_record.file_size is None
        assert file_record.checksum is None
        assert file_record.mime_type == "text/plain"
        assert len(file_record.file_id) == 12

    def test_create_file_with_content(self, session: Session, temp_storage):
        """Test creating file record with content"""
        content = b"Hello, World!"
        file_create = FileCreate(
            filename="test.txt",
            description="Test file",
            file_type=FileType.DOCUMENT,
            entity_type=EntityType.PROJECT,
            entity_id="PROJ001"
        )

        file_record = create_file(session, file_create, content, storage_root=temp_storage)

        assert file_record.file_size == len(content)
        assert file_record.checksum == calculate_file_checksum(content)

        # Check that file was actually written
        file_path = Path(temp_storage) / file_record.file_path
        assert file_path.exists()
        assert file_path.read_bytes() == content

    def test_get_file(self, session: Session, temp_storage):
        """Test getting file by file_id"""
        file_create = FileCreate(
            filename="test.txt",
            entity_type=EntityType.PROJECT,
            entity_id="PROJ001"
        )

        created_file = create_file(session, file_create, storage_root=temp_storage)
        retrieved_file = get_file(session, created_file.file_id)

        assert retrieved_file.id == created_file.id
        assert retrieved_file.file_id == created_file.file_id
        assert retrieved_file.filename == created_file.filename

    def test_get_file_not_found(self, session: Session):
        """Test getting non-existent file"""
        with pytest.raises(Exception) as exc_info:
            get_file(session, "nonexistent")

        assert "not found" in str(exc_info.value)

    def test_update_file(self, session: Session, temp_storage):
        """Test updating file metadata"""
        file_create = FileCreate(
            filename="test.txt",
            description="Original description",
            entity_type=EntityType.PROJECT,
            entity_id="PROJ001"
        )

        created_file = create_file(session, file_create, storage_root=temp_storage)

        file_update = FileUpdate(
            filename="updated.txt",
            description="Updated description",
            is_public=True
        )

        updated_file = update_file(session, created_file.file_id, file_update)

        assert updated_file.filename == "updated.txt"
        assert updated_file.description == "Updated description"
        assert updated_file.is_public is True

    def test_delete_file(self, session: Session, temp_storage):
        """Test deleting file and content"""
        content = b"Hello, World!"
        file_create = FileCreate(
            filename="test.txt",
            entity_type=EntityType.PROJECT,
            entity_id="PROJ001"
        )

        created_file = create_file(session, file_create, content, storage_root=temp_storage)
        file_path = Path(temp_storage) / created_file.file_path

        # Verify file exists
        assert file_path.exists()

        # Delete file
        result = delete_file(session, created_file.file_id, storage_root=temp_storage)
        assert result is True

        # Verify file is deleted
        assert not file_path.exists()

        # Verify database record is deleted
        with pytest.raises(Exception):
            get_file(session, created_file.file_id)

    def test_list_files_empty(self, session: Session):
        """Test listing files when none exist"""
        result = list_files(session)

        assert result.total_items == 0
        assert result.total_pages == 0
        assert result.current_page == 1
        assert result.per_page == 20
        assert result.has_next is False
        assert result.has_prev is False
        assert len(result.data) == 0

    def test_list_files_with_data(self, session: Session, temp_storage):
        """Test listing files with data"""
        # Create test files
        for i in range(3):
            file_create = FileCreate(
                filename=f"test{i}.txt",
                description=f"Test file {i}",
                entity_type=EntityType.PROJECT,
                entity_id="PROJ001",
                file_type=FileType.DOCUMENT
            )
            create_file(session, file_create, storage_root=temp_storage)

        result = list_files(session)

        assert result.total_items == 3
        assert result.total_pages == 1
        assert result.current_page == 1
        assert result.per_page == 20
        assert result.has_next is False
        assert result.has_prev is False
        assert len(result.data) == 3

    def test_list_files_for_entity(self, session: Session, temp_storage):
        """Test listing files for specific entity"""
        # Create files for different entities
        for entity_id in ["PROJ001", "PROJ002"]:
            for i in range(2):
                file_create = FileCreate(
                    filename=f"test{i}.txt",
                    entity_type=EntityType.PROJECT,
                    entity_id=entity_id
                )
                create_file(session, file_create, storage_root=temp_storage)

        # List files for PROJ001
        result = list_files_for_entity(session, EntityType.PROJECT, "PROJ001")

        assert result.total_items == 2
        assert all(file.entity_id == "PROJ001" for file in result.data)

    def test_get_file_count_for_entity(self, session: Session, temp_storage):
        """Test getting file count for entity"""
        # Create files for entity
        for i in range(3):
            file_create = FileCreate(
                filename=f"test{i}.txt",
                entity_type=EntityType.PROJECT,
                entity_id="PROJ001"
            )
            create_file(session, file_create, storage_root=temp_storage)

        count = get_file_count_for_entity(session, EntityType.PROJECT, "PROJ001")
        assert count == 3

    def test_get_file_content(self, session: Session, temp_storage):
        """Test retrieving file content"""
        content = b"Hello, World!"
        file_create = FileCreate(
            filename="test.txt",
            entity_type=EntityType.PROJECT,
            entity_id="PROJ001"
        )

        created_file = create_file(session, file_create, content, storage_root=temp_storage)
        retrieved_content = get_file_content(
            session, created_file.file_id, storage_root=temp_storage
        )

        assert retrieved_content == content

    def test_get_file_content_not_found(self, session: Session, temp_storage):
        """Test retrieving content for non-existent file"""
        file_create = FileCreate(
            filename="test.txt",
            entity_type=EntityType.PROJECT,
            entity_id="PROJ001"
        )

        # Create file record without content
        created_file = create_file(session, file_create, storage_root=temp_storage)

        with pytest.raises(Exception) as exc_info:
            get_file_content(session, created_file.file_id, storage_root=temp_storage)

        assert "not found" in str(exc_info.value)


class TestFileAPI:
    """Test file API endpoints"""

    def test_create_file_endpoint(self, client: TestClient, session: Session):
        """Test file creation endpoint"""
        # This would test the actual API endpoint once routes are implemented
        # For now, we'll skip this as routes.py needs to be updated
        pass

    def test_get_files_endpoint(self, client: TestClient, session: Session):
        """Test file listing endpoint"""
        # This would test the actual API endpoint once routes are implemented
        pass

    def test_get_file_endpoint(self, client: TestClient, session: Session):
        """Test file retrieval endpoint"""
        # This would test the actual API endpoint once routes are implemented
        pass

    def test_update_file_endpoint(self, client: TestClient, session: Session):
        """Test file update endpoint"""
        # This would test the actual API endpoint once routes are implemented
        pass

    def test_delete_file_endpoint(self, client: TestClient, session: Session):
        """Test file deletion endpoint"""
        # This would test the actual API endpoint once routes are implemented
        pass


class TestFileIntegration:
    """Integration tests for file operations"""

    @pytest.fixture
    def temp_storage(self):
        """Create temporary storage directory"""
        temp_dir = tempfile.mkdtemp()
        yield temp_dir
        shutil.rmtree(temp_dir)

    def test_complete_file_lifecycle(self, session: Session, temp_storage):
        """Test complete file lifecycle: create, read, update, delete"""
        content = b"Initial content"

        # Create file
        file_create = FileCreate(
            filename="lifecycle.txt",
            description="Lifecycle test file",
            file_type=FileType.DOCUMENT,
            entity_type=EntityType.PROJECT,
            entity_id="PROJ001",
            created_by="testuser"
        )

        created_file = create_file(session, file_create, content, storage_root=temp_storage)
        assert created_file.filename == "lifecycle.txt"
        assert created_file.file_size == len(content)

        # Read file
        retrieved_file = get_file(session, created_file.file_id)
        assert retrieved_file.id == created_file.id

        retrieved_content = get_file_content(
            session, created_file.file_id, storage_root=temp_storage
        )
        assert retrieved_content == content

        # Update file metadata
        file_update = FileUpdate(
            description="Updated lifecycle test file",
            is_public=True
        )

        updated_file = update_file(session, created_file.file_id, file_update)
        assert updated_file.description == "Updated lifecycle test file"
        assert updated_file.is_public is True

        # Delete file
        result = delete_file(session, created_file.file_id, storage_root=temp_storage)
        assert result is True

        # Verify deletion
        with pytest.raises(Exception):
            get_file(session, created_file.file_id)

    def test_multiple_entities_file_management(self, session: Session, temp_storage):
        """Test file management across multiple entities"""
        entities = [
            (EntityType.PROJECT, "PROJ001"),
            (EntityType.PROJECT, "PROJ002"),
            (EntityType.RUN, "190110_MACHINE123_0001_FLOWCELL123")
        ]

        created_files = []

        # Create files for different entities
        for entity_type, entity_id in entities:
            for i in range(2):
                file_create = FileCreate(
                    filename=f"file{i}.txt",
                    entity_type=entity_type,
                    entity_id=entity_id,
                    file_type=FileType.DOCUMENT
                )

                file_record = create_file(session, file_create, storage_root=temp_storage)
                created_files.append(file_record)

        # Verify total count
        all_files = list_files(session)
        assert all_files.total_items == 6

        # Verify entity-specific counts
        for entity_type, entity_id in entities:
            entity_files = list_files_for_entity(session, entity_type, entity_id)
            assert entity_files.total_items == 2

            count = get_file_count_for_entity(session, entity_type, entity_id)
            assert count == 2

    def test_file_type_filtering(self, session: Session, temp_storage):
        """Test filtering files by type"""
        file_types = [FileType.FASTQ, FileType.BAM, FileType.VCF, FileType.DOCUMENT]

        # Create files of different types
        for file_type in file_types:
            file_create = FileCreate(
                filename=f"test.{file_type.value}",
                entity_type=EntityType.PROJECT,
                entity_id="PROJ001",
                file_type=file_type
            )
            create_file(session, file_create, storage_root=temp_storage)

        # Test filtering by each type
        for file_type in file_types:
            from api.files.models import FileFilters
            filters = FileFilters(file_type=file_type)
            result = list_files(session, filters=filters)

            assert result.total_items == 1
            assert result.data[0].file_type == file_type
