"""
Tests for DELETE /api/v1/files/{file_id} (admin-only)
"""

import uuid

from fastapi.testclient import TestClient
from sqlmodel import Session, select

from api.project.models import Project
from api.project.services import generate_project_id
from api.samples.models import Sample
from api.files.models import (
    File,
    FileHash,
    FileTag,
    FileSample,
    FileProject,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _create_project(session: Session) -> Project:
    project = Project(name="File Delete Test Project")
    project.project_id = generate_project_id(session=session)
    project.attributes = []
    session.add(project)
    session.commit()
    session.refresh(project)
    return project


def _create_file_with_associations(session: Session) -> tuple[File, Project]:
    """Create a file with hashes, tags, sample link, and project association."""
    project = _create_project(session)

    # Create a sample to link
    sample = Sample(sample_id="SAMP-FILE-001", project_id=project.project_id)
    session.add(sample)
    session.flush()

    # Create the file
    file_record = File(
        uri="s3://bucket/project/test-file.bam",
        original_filename="test-file.bam",
        size=1024,
        storage_backend="S3",
        created_by="testuser",
    )
    session.add(file_record)
    session.flush()

    # Add hash
    file_hash = FileHash(
        file_id=file_record.id, algorithm="sha256", value="abc123"
    )
    session.add(file_hash)

    # Add tags
    tag1 = FileTag(file_id=file_record.id, key="type", value="alignment")
    tag2 = FileTag(file_id=file_record.id, key="format", value="bam")
    session.add_all([tag1, tag2])

    # Add sample association
    file_sample = FileSample(
        file_id=file_record.id, sample_id=sample.id, role="tumor"
    )
    session.add(file_sample)

    # Add project association
    file_project = FileProject(
        file_id=file_record.id, project_id=project.id
    )
    session.add(file_project)

    session.commit()
    session.refresh(file_record)

    return file_record, project


# ---------------------------------------------------------------------------
# Admin (superuser) – happy paths
# ---------------------------------------------------------------------------


class TestDeleteFileAdmin:
    """Admin users should be able to delete file records."""

    def test_delete_file_success(
        self, admin_client: TestClient, session: Session
    ):
        """DELETE returns 204 and removes the file from the database."""
        file_record, _ = _create_file_with_associations(session)
        file_uuid = file_record.id

        response = admin_client.delete(f"/api/v1/files/{file_uuid}")
        assert response.status_code == 204

        # Verify file is gone
        assert session.get(File, file_uuid) is None

    def test_delete_file_cascades_hashes(
        self, admin_client: TestClient, session: Session
    ):
        """Deleting a file removes its FileHash rows."""
        file_record, _ = _create_file_with_associations(session)
        file_uuid = file_record.id

        response = admin_client.delete(f"/api/v1/files/{file_uuid}")
        assert response.status_code == 204

        remaining = session.exec(
            select(FileHash).where(FileHash.file_id == file_uuid)
        ).all()
        assert remaining == []

    def test_delete_file_cascades_tags(
        self, admin_client: TestClient, session: Session
    ):
        """Deleting a file removes its FileTag rows."""
        file_record, _ = _create_file_with_associations(session)
        file_uuid = file_record.id

        response = admin_client.delete(f"/api/v1/files/{file_uuid}")
        assert response.status_code == 204

        remaining = session.exec(
            select(FileTag).where(FileTag.file_id == file_uuid)
        ).all()
        assert remaining == []

    def test_delete_file_cascades_sample_links(
        self, admin_client: TestClient, session: Session
    ):
        """Deleting a file removes its FileSample rows."""
        file_record, _ = _create_file_with_associations(session)
        file_uuid = file_record.id

        response = admin_client.delete(f"/api/v1/files/{file_uuid}")
        assert response.status_code == 204

        remaining = session.exec(
            select(FileSample).where(FileSample.file_id == file_uuid)
        ).all()
        assert remaining == []

    def test_delete_file_cascades_project_links(
        self, admin_client: TestClient, session: Session
    ):
        """Deleting a file removes its FileProject rows."""
        file_record, _ = _create_file_with_associations(session)
        file_uuid = file_record.id

        response = admin_client.delete(f"/api/v1/files/{file_uuid}")
        assert response.status_code == 204

        remaining = session.exec(
            select(FileProject).where(FileProject.file_id == file_uuid)
        ).all()
        assert remaining == []

    def test_delete_file_does_not_remove_sample(
        self, admin_client: TestClient, session: Session
    ):
        """Deleting a file does NOT delete the associated sample."""
        file_record, project = _create_file_with_associations(session)

        # Find the sample linked to this file
        link = session.exec(
            select(FileSample).where(FileSample.file_id == file_record.id)
        ).first()
        sample_uuid = link.sample_id

        response = admin_client.delete(f"/api/v1/files/{file_record.id}")
        assert response.status_code == 204

        # The sample itself should still exist
        assert session.get(Sample, sample_uuid) is not None

    def test_delete_file_not_found(self, admin_client: TestClient):
        """DELETE returns 404 for a non-existent file UUID."""
        fake_uuid = uuid.uuid4()
        response = admin_client.delete(f"/api/v1/files/{fake_uuid}")
        assert response.status_code == 404
        assert "not found" in response.json()["detail"].lower()

    def test_delete_minimal_file(
        self, admin_client: TestClient, session: Session
    ):
        """DELETE works for a file with no child associations."""
        file_record = File(uri="s3://bucket/bare-file.txt", storage_backend="S3")
        session.add(file_record)
        session.commit()
        session.refresh(file_record)

        response = admin_client.delete(f"/api/v1/files/{file_record.id}")
        assert response.status_code == 204
        assert session.get(File, file_record.id) is None


# ---------------------------------------------------------------------------
# Non-admin – authorization checks
# ---------------------------------------------------------------------------


class TestDeleteFileNonAdmin:
    """Non-admin users should be rejected with 403."""

    def test_regular_user_cannot_delete_file(
        self, client: TestClient, session: Session
    ):
        """A non-superuser gets 403 Forbidden."""
        file_record, _ = _create_file_with_associations(session)

        response = client.delete(f"/api/v1/files/{file_record.id}")
        assert response.status_code == 403

        # File should still exist
        assert session.get(File, file_record.id) is not None


class TestDeleteFileUnauthenticated:
    """Unauthenticated requests should be rejected."""

    def test_unauthenticated_cannot_delete_file(
        self, unauthenticated_client: TestClient, session: Session
    ):
        """A request with no auth token gets 401."""
        file_record, _ = _create_file_with_associations(session)

        response = unauthenticated_client.delete(
            f"/api/v1/files/{file_record.id}"
        )
        assert response.status_code == 401
