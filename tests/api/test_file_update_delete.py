"""Tests for file PATCH/DELETE and sample DELETE endpoints (superuser-only)."""

import uuid

from sqlmodel import select

from api.files.models import (
    File,
    FileHash,
    FileTag,
    FileSample,
    FileProject,
)
from api.project.models import Project
from api.samples.models import Sample, SampleAttribute
from api.runs.models import SequencingRun, SampleSequencingRun


# ============================================================================
# Helpers
# ============================================================================


def _create_project(session, project_id="P-TEST-001"):
    """Create a test project and return it."""
    project = Project(project_id=project_id, name="Test Project")
    session.add(project)
    session.commit()
    session.refresh(project)
    return project


def _create_file_with_children(session, project, uri="s3://bucket/path/file.txt"):
    """Create a File with hash, tag, sample association, and project association."""
    # Create sample
    sample = Sample(sample_id="SAMPLE-001", project_id=project.project_id)
    session.add(sample)
    session.flush()

    # Create file
    file_record = File(uri=uri, source="test", storage_backend="S3")
    session.add(file_record)
    session.flush()

    # Add hash
    fh = FileHash(file_id=file_record.id, algorithm="md5", value="abc123")
    session.add(fh)

    # Add tag
    ft = FileTag(file_id=file_record.id, key="type", value="alignment")
    session.add(ft)

    # Add project association
    fp = FileProject(file_id=file_record.id, project_id=project.id)
    session.add(fp)

    # Add sample association
    fs = FileSample(file_id=file_record.id, sample_id=sample.id, role="tumor")
    session.add(fs)

    session.commit()
    session.refresh(file_record)
    return file_record, sample


def _create_sample_with_children(session, project, run=None):
    """Create a sample with attributes, file association, and optional run association."""
    sample = Sample(sample_id="SAMPLE-DEL-001", project_id=project.project_id)
    session.add(sample)
    session.flush()

    # Add attribute
    attr = SampleAttribute(sample_id=sample.id, key="tissue", value="blood")
    session.add(attr)

    # Add file + file-sample association
    file_record = File(uri="s3://bucket/path/sample_file.bam", source="test")
    session.add(file_record)
    session.flush()

    fs = FileSample(file_id=file_record.id, sample_id=sample.id, role="normal")
    session.add(fs)

    fp = FileProject(file_id=file_record.id, project_id=project.id)
    session.add(fp)

    # Add run association if run is provided
    if run:
        assoc = SampleSequencingRun(
            sample_id=sample.id,
            sequencing_run_id=run.id,
            created_by="testuser",
        )
        session.add(assoc)

    session.commit()
    session.refresh(sample)
    return sample, file_record


# ============================================================================
# PATCH /api/files/{id} — Update file
# ============================================================================


class TestFilePatch:
    """Tests for PATCH /api/v1/files/{id}."""

    def test_patch_uri_success(self, session, superuser_client):
        """Superuser can update a file's URI."""
        project = _create_project(session)
        file_record, _ = _create_file_with_children(session, project)

        response = superuser_client.patch(
            f"/api/v1/files/{file_record.id}",
            json={"uri": "s3://correct-bucket/path/file.txt"},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["uri"] == "s3://correct-bucket/path/file.txt"
        assert data["id"] == str(file_record.id)
        # Associations should still be present
        assert len(data["associations"]) == 1
        assert len(data["hashes"]) == 1
        assert len(data["tags"]) == 1
        assert len(data["samples"]) == 1

    def test_patch_multiple_fields(self, session, superuser_client):
        """Superuser can update multiple scalar fields at once."""
        project = _create_project(session)
        file_record, _ = _create_file_with_children(session, project)

        response = superuser_client.patch(
            f"/api/v1/files/{file_record.id}",
            json={
                "uri": "s3://new-bucket/new/path.txt",
                "source": "corrected-pipeline",
                "size": 12345,
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert data["uri"] == "s3://new-bucket/new/path.txt"
        assert data["source"] == "corrected-pipeline"
        assert data["size"] == 12345

    def test_patch_empty_body(self, session, superuser_client):
        """Empty update body returns 400."""
        project = _create_project(session)
        file_record, _ = _create_file_with_children(session, project)

        response = superuser_client.patch(
            f"/api/v1/files/{file_record.id}",
            json={},
        )

        assert response.status_code == 400
        assert "No fields to update" in response.json()["detail"]

    def test_patch_nonexistent_file(self, superuser_client):
        """Patching a non-existent file returns 404."""
        fake_id = uuid.uuid4()
        response = superuser_client.patch(
            f"/api/v1/files/{fake_id}",
            json={"uri": "s3://bucket/file.txt"},
        )

        assert response.status_code == 404

    def test_patch_rejects_extra_fields(self, session, superuser_client):
        """Extra fields in the body are rejected (extra='forbid')."""
        project = _create_project(session)
        file_record, _ = _create_file_with_children(session, project)

        response = superuser_client.patch(
            f"/api/v1/files/{file_record.id}",
            json={"uri": "s3://bucket/file.txt", "bogus_field": "nope"},
        )

        assert response.status_code == 422

    def test_patch_forbidden_for_regular_user(self, session, client):
        """Non-superuser gets 403 on PATCH."""
        project = _create_project(session)
        file_record, _ = _create_file_with_children(session, project)

        response = client.patch(
            f"/api/v1/files/{file_record.id}",
            json={"uri": "s3://bucket/file.txt"},
        )

        assert response.status_code == 403


# ============================================================================
# DELETE /api/files/{id} — Delete file
# ============================================================================


class TestFileDelete:
    """Tests for DELETE /api/v1/files/{id}."""

    def test_delete_file_success(self, session, superuser_client):
        """Superuser can delete a file and all child rows cascade."""
        project = _create_project(session)
        file_record, _ = _create_file_with_children(session, project)
        file_id = file_record.id

        response = superuser_client.delete(f"/api/v1/files/{file_id}")

        assert response.status_code == 204

        # Verify file is gone
        assert session.get(File, file_id) is None

        # Verify child rows are gone
        assert session.exec(
            select(FileHash).where(FileHash.file_id == file_id)
        ).first() is None
        assert session.exec(
            select(FileTag).where(FileTag.file_id == file_id)
        ).first() is None
        assert session.exec(
            select(FileSample).where(FileSample.file_id == file_id)
        ).first() is None
        assert session.exec(
            select(FileProject).where(FileProject.file_id == file_id)
        ).first() is None

    def test_delete_nonexistent_file(self, superuser_client):
        """Deleting a non-existent file returns 404."""
        fake_id = uuid.uuid4()
        response = superuser_client.delete(f"/api/v1/files/{fake_id}")

        assert response.status_code == 404

    def test_delete_forbidden_for_regular_user(self, session, client):
        """Non-superuser gets 403 on DELETE."""
        project = _create_project(session)
        file_record, _ = _create_file_with_children(session, project)

        response = client.delete(f"/api/v1/files/{file_record.id}")

        assert response.status_code == 403

    def test_delete_file_preserves_sample(self, session, superuser_client):
        """Deleting a file removes the FileSample junction but not the Sample."""
        project = _create_project(session)
        file_record, sample = _create_file_with_children(session, project)
        file_id = file_record.id
        sample_id = sample.id

        response = superuser_client.delete(f"/api/v1/files/{file_id}")

        assert response.status_code == 204
        # Sample should still exist
        assert session.get(Sample, sample_id) is not None


# ============================================================================
# DELETE /api/projects/{project_id}/samples/{sample_id} — Delete sample
# ============================================================================


class TestSampleDelete:
    """Tests for DELETE /api/v1/projects/{project_id}/samples/{sample_id}."""

    def test_delete_sample_success(self, session, superuser_client):
        """Superuser can delete a sample and all child rows."""
        project = _create_project(session)
        sample, file_record = _create_sample_with_children(session, project)
        sample_uuid = sample.id

        response = superuser_client.delete(
            f"/api/v1/projects/{project.project_id}/samples/{sample.sample_id}"
        )

        assert response.status_code == 204

        # Verify sample is gone
        assert session.get(Sample, sample_uuid) is None

        # Verify SampleAttribute is gone
        assert session.exec(
            select(SampleAttribute).where(SampleAttribute.sample_id == sample_uuid)
        ).first() is None

        # Verify FileSample junction is gone
        assert session.exec(
            select(FileSample).where(FileSample.sample_id == sample_uuid)
        ).first() is None

    def test_delete_sample_preserves_file(self, session, superuser_client):
        """Deleting a sample removes FileSample but NOT the File record."""
        project = _create_project(session)
        sample, file_record = _create_sample_with_children(session, project)
        file_id = file_record.id

        response = superuser_client.delete(
            f"/api/v1/projects/{project.project_id}/samples/{sample.sample_id}"
        )

        assert response.status_code == 204
        # File should still exist
        assert session.get(File, file_id) is not None

    def test_delete_sample_with_run_association(self, session, superuser_client):
        """Deleting a sample also removes SampleSequencingRun junctions."""
        from datetime import date

        project = _create_project(session)
        run = SequencingRun(
            run_id="240101_M00001_0001_000000000-A1B2C",
            run_date=date(2024, 1, 1),
            machine_id="M00001",
            run_number="0001",
            flowcell_id="000000000-A1B2C",
        )
        session.add(run)
        session.commit()
        session.refresh(run)

        sample, _ = _create_sample_with_children(session, project, run=run)
        sample_uuid = sample.id

        response = superuser_client.delete(
            f"/api/v1/projects/{project.project_id}/samples/{sample.sample_id}"
        )

        assert response.status_code == 204

        # Verify SampleSequencingRun is gone
        assert session.exec(
            select(SampleSequencingRun).where(
                SampleSequencingRun.sample_id == sample_uuid
            )
        ).first() is None

    def test_delete_nonexistent_sample(self, session, superuser_client):
        """Deleting a non-existent sample returns 404."""
        project = _create_project(session)

        response = superuser_client.delete(
            f"/api/v1/projects/{project.project_id}/samples/NONEXISTENT"
        )

        assert response.status_code == 404

    def test_delete_sample_wrong_project(self, session, superuser_client):
        """Deleting a sample from a wrong project returns 404."""
        project1 = _create_project(session, "P-PROJ-001")
        project2 = _create_project(session, "P-PROJ-002")
        sample, _ = _create_sample_with_children(session, project1)

        response = superuser_client.delete(
            f"/api/v1/projects/{project2.project_id}/samples/{sample.sample_id}"
        )

        assert response.status_code == 404

    def test_delete_sample_forbidden_for_regular_user(self, session, client):
        """Non-superuser gets 403 on DELETE."""
        project = _create_project(session)
        sample, _ = _create_sample_with_children(session, project)

        response = client.delete(
            f"/api/v1/projects/{project.project_id}/samples/{sample.sample_id}"
        )

        assert response.status_code == 403
