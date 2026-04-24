"""Integration tests for POST /projects/{project_id}/samples/upload."""

from io import BytesIO

from fastapi.testclient import TestClient
from sqlmodel import Session, select

from api.project.models import Project
from api.project.services import generate_project_id
from api.samples.models import Sample, SampleAttribute


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _create_project(session: Session, name: str = "Upload Test Project") -> str:
    """Create a project and return its project_id."""
    project = Project(name=name)
    project.project_id = generate_project_id(session=session)
    project.attributes = []
    session.add(project)
    session.commit()
    session.refresh(project)
    return project.project_id


def _upload(client: TestClient, project_id: str, csv_content: str,
            filename: str = "samples.csv"):
    """Helper to POST a file upload to the samples/upload endpoint."""
    return client.post(
        f"/api/v1/projects/{project_id}/samples/upload",
        files={"file": (filename, BytesIO(csv_content.encode()), "text/csv")},
    )


# ===================================================================
# Happy-path tests
# ===================================================================


class TestSampleUploadHappyPath:
    """POST /projects/{project_id}/samples/upload — happy path."""

    def test_upload_csv_creates_samples(
        self, client: TestClient, session: Session
    ):
        """Test that uploading a CSV file creates samples with the correct
        attributes persisted in the database."""
        pid = _create_project(session)
        csv = "SampleName,Tissue,Condition\nS001,Liver,Healthy\nS002,Heart,Diseased\n"

        response = _upload(client, pid, csv)

        assert response.status_code == 201
        body = response.json()
        assert body["project_id"] == pid
        assert body["samples_created"] == 2
        assert len(body["items"]) == 2

        # Verify attributes in DB
        sample = session.exec(
            select(Sample).where(
                Sample.sample_id == "S001", Sample.project_id == pid
            )
        ).one()
        attrs = session.exec(
            select(SampleAttribute).where(
                SampleAttribute.sample_id == sample.id
            )
        ).all()
        attr_dict = {a.key: a.value for a in attrs}
        assert attr_dict == {"Tissue": "Liver", "Condition": "Healthy"}

    def test_upload_tsv_creates_samples(
        self, client: TestClient, session: Session
    ):
        """Test that uploading a TSV file auto-detects the tab delimiter
        and creates the expected number of samples."""
        pid = _create_project(session)
        tsv = "SampleName\tTissue\nS001\tLiver\nS002\tHeart\n"

        response = _upload(client, pid, tsv, filename="samples.tsv")

        assert response.status_code == 201
        assert response.json()["samples_created"] == 2

    def test_upload_upsert_existing_samples(
        self, client: TestClient, session: Session
    ):
        """Test that uploading a file for an existing sample upserts changed
        attributes, adds new attributes, and preserves unmentioned attributes."""
        pid = _create_project(session)

        # First upload
        csv1 = "SampleName,Tissue,Condition\nS001,Liver,Healthy\n"
        r1 = _upload(client, pid, csv1)
        assert r1.status_code == 201
        assert r1.json()["samples_created"] == 1

        # Second upload — change Tissue, add Stage
        csv2 = "SampleName,Tissue,Stage\nS001,Heart,III\n"
        r2 = _upload(client, pid, csv2)
        assert r2.status_code == 201
        b2 = r2.json()
        assert b2["samples_created"] == 0
        assert b2["samples_updated"] == 1

        # Verify DB: Tissue updated, Condition preserved, Stage added
        sample = session.exec(
            select(Sample).where(
                Sample.sample_id == "S001", Sample.project_id == pid
            )
        ).one()
        attrs = session.exec(
            select(SampleAttribute).where(
                SampleAttribute.sample_id == sample.id
            )
        ).all()
        attr_dict = {a.key: a.value for a in attrs}
        assert attr_dict == {
            "Tissue": "Heart",
            "Condition": "Healthy",
            "Stage": "III",
        }

    def test_upload_samplename_only(
        self, client: TestClient, session: Session
    ):
        """Test that uploading a file with only a SampleName column creates
        samples with no attributes."""
        pid = _create_project(session)
        csv = "SampleName\nS001\nS002\n"

        response = _upload(client, pid, csv)
        assert response.status_code == 201
        assert response.json()["samples_created"] == 2

    def test_upload_case_insensitive_header(
        self, client: TestClient, session: Session
    ):
        """Test that the 'sample_name' column header variant (lowercase
        with underscore) is recognized and samples are created."""
        pid = _create_project(session)
        csv = "sample_name,Tissue\nS001,Liver\n"

        response = _upload(client, pid, csv)
        assert response.status_code == 201
        assert response.json()["samples_created"] == 1

    def test_upload_empty_cell_deletes_existing_attribute(
        self, client: TestClient, session: Session
    ):
        """Test that uploading a CSV where a column is present but the
        cell is empty deletes the previously-set attribute from the DB,
        while attributes for columns absent from the file are preserved."""
        pid = _create_project(session)

        # First upload — set Tissue and Condition
        csv1 = "SampleName,Tissue,Condition\nS001,Liver,Healthy\n"
        r1 = _upload(client, pid, csv1)
        assert r1.status_code == 201
        assert r1.json()["samples_created"] == 1

        # Second upload — Tissue column present but empty, Stage added,
        # Condition column absent (should be preserved)
        csv2 = "SampleName,Tissue,Stage\nS001,,III\n"
        r2 = _upload(client, pid, csv2)
        assert r2.status_code == 201
        assert r2.json()["samples_updated"] == 1

        # Verify DB: Tissue deleted, Condition preserved, Stage added
        sample = session.exec(
            select(Sample).where(
                Sample.sample_id == "S001", Sample.project_id == pid
            )
        ).one()
        attrs = session.exec(
            select(SampleAttribute).where(
                SampleAttribute.sample_id == sample.id
            )
        ).all()
        attr_dict = {a.key: a.value for a in attrs}
        assert "Tissue" not in attr_dict, "Empty cell should delete existing attribute"
        assert attr_dict["Condition"] == "Healthy", "Absent column should preserve attribute"
        assert attr_dict["Stage"] == "III"

    def test_upload_empty_cell_on_new_sample_skips_attribute(
        self, client: TestClient, session: Session
    ):
        """Test that uploading a CSV for a new sample where a column cell
        is empty does not create an attribute row for that column."""
        pid = _create_project(session)
        csv = "SampleName,Tissue,Condition\nS001,Liver,\n"

        response = _upload(client, pid, csv)
        assert response.status_code == 201
        assert response.json()["samples_created"] == 1

        sample = session.exec(
            select(Sample).where(
                Sample.sample_id == "S001", Sample.project_id == pid
            )
        ).one()
        attrs = session.exec(
            select(SampleAttribute).where(
                SampleAttribute.sample_id == sample.id
            )
        ).all()
        attr_dict = {a.key: a.value for a in attrs}
        assert attr_dict == {"Tissue": "Liver"}
        assert "Condition" not in attr_dict


# ===================================================================
# Error cases
# ===================================================================


class TestSampleUploadErrors:
    """POST /projects/{project_id}/samples/upload — error handling."""

    def test_upload_invalid_extension(
        self, client: TestClient, session: Session
    ):
        """Test that uploading a file with an unsupported extension (.xlsx)
        returns HTTP 400 with an 'Unsupported file type' error message."""
        pid = _create_project(session)
        response = _upload(client, pid, "SampleName\nS001\n", filename="samples.xlsx")
        assert response.status_code == 400
        assert "Unsupported file type" in response.json()["detail"]

    def test_upload_missing_samplename_column(
        self, client: TestClient, session: Session
    ):
        """Test that uploading a file without a recognized SampleName column
        returns HTTP 400 with an error mentioning the expected column name."""
        pid = _create_project(session)
        response = _upload(client, pid, "Name,Tissue\nS001,Liver\n")
        assert response.status_code == 400
        assert "SampleName" in response.json()["detail"]

    def test_upload_duplicate_sample_names(
        self, client: TestClient, session: Session
    ):
        """Test that uploading a file containing duplicate sample names
        returns HTTP 400 with an error identifying the duplicate."""
        pid = _create_project(session)
        csv = "SampleName,Tissue\nS001,Liver\nS001,Heart\n"
        response = _upload(client, pid, csv)
        assert response.status_code == 400
        assert "duplicate" in response.json()["detail"].lower()

    def test_upload_nonexistent_project(
        self, client: TestClient, session: Session
    ):
        """Test that uploading a file to a non-existent project returns
        HTTP 404."""
        csv = "SampleName\nS001\n"
        response = _upload(client, "P-NONEXISTENT-9999", csv)
        assert response.status_code == 404

    def test_upload_empty_file(
        self, client: TestClient, session: Session
    ):
        """Test that uploading an empty file returns HTTP 400 with an
        error indicating the file is empty."""
        pid = _create_project(session)
        response = _upload(client, pid, "", filename="empty.csv")
        assert response.status_code == 400
        assert "empty" in response.json()["detail"].lower()
