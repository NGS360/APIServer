"""
Tests for DELETE /api/v1/samples/{sample_id} (admin-only)
"""

import uuid

from fastapi.testclient import TestClient
from sqlmodel import Session, select

from api.project.models import Project
from api.project.services import generate_project_id
from api.samples.models import Sample, SampleAttribute
from api.files.models import File, FileSample
from api.runs.models import SequencingRun, SampleSequencingRun


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _create_project(session: Session) -> Project:
    project = Project(name="Delete Test Project")
    project.project_id = generate_project_id(session=session)
    project.attributes = []
    session.add(project)
    session.commit()
    session.refresh(project)
    return project


def _create_sample_with_attrs(session: Session, project: Project) -> Sample:
    sample = Sample(sample_id="SAMP-001", project_id=project.project_id)
    session.add(sample)
    session.flush()

    attr1 = SampleAttribute(sample_id=sample.id, key="Tissue", value="Liver")
    attr2 = SampleAttribute(sample_id=sample.id, key="Disease", value="HCC")
    session.add_all([attr1, attr2])
    session.commit()
    session.refresh(sample)
    return sample


def _create_run(session: Session) -> SequencingRun:
    from datetime import date

    run = SequencingRun(
        run_date=date(2024, 1, 15),
        machine_id="M00001",
        run_number="0001",
        flowcell_id="HFLOWCELL",
    )
    session.add(run)
    session.commit()
    session.refresh(run)
    return run


# ---------------------------------------------------------------------------
# Admin (superuser) – happy paths
# ---------------------------------------------------------------------------


class TestDeleteSampleAdmin:
    """Admin users should be able to delete samples."""

    def test_delete_sample_success(
        self, admin_client: TestClient, session: Session
    ):
        """DELETE returns 204 and removes the sample from the database."""
        project = _create_project(session)
        sample = _create_sample_with_attrs(session, project)
        sample_uuid = sample.id

        response = admin_client.delete(f"/api/v1/samples/{sample_uuid}")
        assert response.status_code == 204

        # Verify sample is gone
        assert session.get(Sample, sample_uuid) is None

    def test_delete_sample_removes_attributes(
        self, admin_client: TestClient, session: Session
    ):
        """Deleting a sample also removes its SampleAttribute rows."""
        project = _create_project(session)
        sample = _create_sample_with_attrs(session, project)
        sample_uuid = sample.id

        response = admin_client.delete(f"/api/v1/samples/{sample_uuid}")
        assert response.status_code == 204

        remaining_attrs = session.exec(
            select(SampleAttribute).where(SampleAttribute.sample_id == sample_uuid)
        ).all()
        assert remaining_attrs == []

    def test_delete_sample_removes_file_sample_links(
        self, admin_client: TestClient, session: Session
    ):
        """Deleting a sample removes FileSample junction rows."""
        project = _create_project(session)
        sample = _create_sample_with_attrs(session, project)
        sample_uuid = sample.id

        # Create a file linked to the sample
        file_record = File(uri="s3://bucket/test.bam", storage_backend="S3")
        session.add(file_record)
        session.flush()

        link = FileSample(
            file_id=file_record.id, sample_id=sample_uuid, role="tumor"
        )
        session.add(link)
        session.commit()

        response = admin_client.delete(f"/api/v1/samples/{sample_uuid}")
        assert response.status_code == 204

        # FileSample row should be gone
        remaining = session.exec(
            select(FileSample).where(FileSample.sample_id == sample_uuid)
        ).all()
        assert remaining == []

        # The file itself should still exist
        assert session.get(File, file_record.id) is not None

    def test_delete_sample_removes_run_associations(
        self, admin_client: TestClient, session: Session
    ):
        """Deleting a sample removes SampleSequencingRun associations."""
        project = _create_project(session)
        sample = _create_sample_with_attrs(session, project)
        sample_uuid = sample.id
        run = _create_run(session)

        assoc = SampleSequencingRun(
            sample_id=sample_uuid,
            sequencing_run_id=run.id,
            created_by="testuser",
        )
        session.add(assoc)
        session.commit()

        response = admin_client.delete(f"/api/v1/samples/{sample_uuid}")
        assert response.status_code == 204

        remaining = session.exec(
            select(SampleSequencingRun).where(
                SampleSequencingRun.sample_id == sample_uuid
            )
        ).all()
        assert remaining == []

    def test_delete_sample_not_found(
        self, admin_client: TestClient
    ):
        """DELETE returns 404 for a non-existent sample UUID."""
        fake_uuid = uuid.uuid4()
        response = admin_client.delete(f"/api/v1/samples/{fake_uuid}")
        assert response.status_code == 404
        assert "not found" in response.json()["detail"].lower()


# ---------------------------------------------------------------------------
# Non-admin – authorization checks
# ---------------------------------------------------------------------------


class TestDeleteSampleNonAdmin:
    """Non-admin users should be rejected with 403."""

    def test_regular_user_cannot_delete_sample(
        self, client: TestClient, session: Session
    ):
        """A non-superuser gets 403 Forbidden."""
        project = _create_project(session)
        sample = _create_sample_with_attrs(session, project)

        response = client.delete(f"/api/v1/samples/{sample.id}")
        assert response.status_code == 403

        # Sample should still exist
        assert session.get(Sample, sample.id) is not None


class TestDeleteSampleUnauthenticated:
    """Unauthenticated requests should be rejected."""

    def test_unauthenticated_cannot_delete_sample(
        self, unauthenticated_client: TestClient, session: Session
    ):
        """A request with no auth token gets 401."""
        project = _create_project(session)
        sample = _create_sample_with_attrs(session, project)

        response = unauthenticated_client.delete(
            f"/api/v1/samples/{sample.id}"
        )
        assert response.status_code == 401
