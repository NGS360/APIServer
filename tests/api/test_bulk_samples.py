"""Tests for single-sample run_id enrichment and bulk sample creation endpoint."""

from datetime import date

from fastapi.testclient import TestClient
from sqlmodel import Session, select

from api.project.models import Project
from api.project.services import generate_project_id
from api.runs.models import SequencingRun, SampleSequencingRun
from api.samples.models import Sample, SampleAttribute
from api.files.models import File, FileSample, FileProject, FileHash, FileTag


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _create_project(session: Session, name: str = "Test Project") -> str:
    """Create a project and return its project_id."""
    project = Project(name=name)
    project.project_id = generate_project_id(session=session)
    project.attributes = []
    session.add(project)
    session.commit()
    session.refresh(project)
    return project.project_id


def _create_run(
    session: Session,
    *,
    run_id: str = "240315_M00001_0042_HXXXXXXXXX",
    run_date: date = date(2024, 3, 15),
    machine_id: str = "M00001",
    run_number: int = 42,
    flowcell_id: str = "HXXXXXXXXX",
    experiment_name: str = "TestExp",
) -> str:
    """Insert a sequencing run and return its run_id."""
    run = SequencingRun(
        run_id=run_id,
        run_date=run_date,
        machine_id=machine_id,
        run_number=run_number,
        flowcell_id=flowcell_id,
        experiment_name=experiment_name,
    )
    session.add(run)
    session.commit()
    session.refresh(run)
    return run.run_id


def _create_second_run(session: Session) -> str:
    """Insert a second, distinct sequencing run."""
    return _create_run(
        session,
        run_id="240420_M00002_0099_JYYYYYYYYY",
        run_date=date(2024, 4, 20),
        machine_id="M00002",
        run_number=99,
        flowcell_id="JYYYYYYYYY",
        experiment_name="TestExp2",
    )


# ===================================================================
# Single-sample endpoint with run_id
# ===================================================================


class TestSingleSampleWithRunId:
    """POST /projects/{project_id}/samples with optional run_id."""

    def test_create_sample_with_run_id(
        self, client: TestClient, session: Session
    ):
        """Test that a sample and SampleSequencingRun are created in one call."""
        pid = _create_project(session)
        run_id = _create_run(session)

        response = client.post(
            f"/api/v1/projects/{pid}/samples",
            json={
                "sample_id": "S001",
                "run_id": run_id,
                "attributes": [{"key": "Tissue", "value": "Liver"}],
            },
        )
        assert response.status_code == 201
        body = response.json()
        assert body["sample_id"] == "S001"
        assert body["project_id"] == pid
        assert body["run_id"] == run_id

        # Verify the association was persisted
        sample = session.exec(
            select(Sample).where(
                Sample.sample_id == "S001", Sample.project_id == pid
            )
        ).one()
        assoc = session.exec(
            select(SampleSequencingRun).where(
                SampleSequencingRun.sample_id == sample.id
            )
        ).first()
        assert assoc is not None
        assert assoc.created_by == "testuser"

    def test_create_sample_without_run_id(
        self, client: TestClient, session: Session
    ):
        """Test that a sample is created successfully when run_id is omitted."""
        pid = _create_project(session)

        response = client.post(
            f"/api/v1/projects/{pid}/samples",
            json={"sample_id": "S002"},
        )
        assert response.status_code == 201
        body = response.json()
        assert body["sample_id"] == "S002"
        assert body["run_id"] is None

        # No association created
        sample = session.exec(
            select(Sample).where(
                Sample.sample_id == "S002", Sample.project_id == pid
            )
        ).one()
        assocs = session.exec(
            select(SampleSequencingRun).where(
                SampleSequencingRun.sample_id == sample.id
            )
        ).all()
        assert len(assocs) == 0

    def test_create_sample_with_invalid_run_id(
        self, client: TestClient, session: Session
    ):
        """Test that an invalid run_id returns 404; no sample is created."""
        pid = _create_project(session)

        response = client.post(
            f"/api/v1/projects/{pid}/samples",
            json={
                "sample_id": "S003",
                "run_id": "240101_XFAKE_0001_ZZZZZZZZZZ",
            },
        )
        assert response.status_code == 404
        assert "not found" in response.json()["detail"].lower()

        # Sample should NOT have been created
        sample = session.exec(
            select(Sample).where(
                Sample.sample_id == "S003", Sample.project_id == pid
            )
        ).first()
        assert sample is None

    def test_create_sample_with_null_run_id(
        self, client: TestClient, session: Session
    ):
        """Test that explicitly passing null run_id is the same as omitting it."""
        pid = _create_project(session)

        response = client.post(
            f"/api/v1/projects/{pid}/samples",
            json={"sample_id": "S004", "run_id": None},
        )
        assert response.status_code == 201
        assert response.json()["run_id"] is None


# ===================================================================
# Bulk sample creation endpoint
# ===================================================================


class TestBulkSampleCreation:
    """POST /projects/{project_id}/samples/bulk."""

    # ----- Happy-path / basic -----

    def test_bulk_create_basic(self, client: TestClient, session: Session):
        """Test that multiple samples can be created without run associations."""
        pid = _create_project(session)

        response = client.post(
            f"/api/v1/projects/{pid}/samples/bulk",
            json={
                "samples": [
                    {"sample_id": "B001"},
                    {"sample_id": "B002"},
                    {"sample_id": "B003"},
                ]
            },
        )
        assert response.status_code == 201
        body = response.json()
        assert body["project_id"] == pid
        assert body["samples_created"] == 3
        assert body["samples_existing"] == 0
        assert body["associations_created"] == 0
        assert body["associations_existing"] == 0
        assert len(body["items"]) == 3
        assert all(item["created"] is True for item in body["items"])

    def test_bulk_create_with_run_id(
        self, client: TestClient, session: Session
    ):
        """Test that all samples are associated with a run in one call."""
        pid = _create_project(session)
        run_id = _create_run(session)

        response = client.post(
            f"/api/v1/projects/{pid}/samples/bulk",
            json={
                "samples": [
                    {"sample_id": "R001", "run_id": run_id},
                    {"sample_id": "R002", "run_id": run_id},
                ]
            },
        )
        assert response.status_code == 201
        body = response.json()
        assert body["samples_created"] == 2
        assert body["associations_created"] == 2
        for item in body["items"]:
            assert item["run_id"] == run_id

        # Verify associations in DB
        for sid in ("R001", "R002"):
            sample = session.exec(
                select(Sample).where(
                    Sample.sample_id == sid, Sample.project_id == pid
                )
            ).one()
            assoc = session.exec(
                select(SampleSequencingRun).where(
                    SampleSequencingRun.sample_id == sample.id
                )
            ).first()
            assert assoc is not None

    def test_bulk_create_with_attributes(
        self, client: TestClient, session: Session
    ):
        """Test that attributes are persisted for each sample in the batch."""
        pid = _create_project(session)

        response = client.post(
            f"/api/v1/projects/{pid}/samples/bulk",
            json={
                "samples": [
                    {
                        "sample_id": "A001",
                        "attributes": [
                            {"key": "Tissue", "value": "Liver"},
                            {"key": "Condition", "value": "Healthy"},
                        ],
                    },
                    {
                        "sample_id": "A002",
                        "attributes": [
                            {"key": "Tissue", "value": "Heart"},
                        ],
                    },
                ]
            },
        )
        assert response.status_code == 201
        assert response.json()["samples_created"] == 2

        # Verify attributes persisted
        s1 = session.exec(
            select(Sample).where(
                Sample.sample_id == "A001", Sample.project_id == pid
            )
        ).one()
        attrs1 = session.exec(
            select(SampleAttribute).where(
                SampleAttribute.sample_id == s1.id
            )
        ).all()
        assert len(attrs1) == 2
        keys = {a.key for a in attrs1}
        assert keys == {"Tissue", "Condition"}

        s2 = session.exec(
            select(Sample).where(
                Sample.sample_id == "A002", Sample.project_id == pid
            )
        ).one()
        attrs2 = session.exec(
            select(SampleAttribute).where(
                SampleAttribute.sample_id == s2.id
            )
        ).all()
        assert len(attrs2) == 1
        assert attrs2[0].key == "Tissue"
        assert attrs2[0].value == "Heart"

    # ----- Idempotency -----

    def test_bulk_idempotent_resubmission(
        self, client: TestClient, session: Session
    ):
        """Test that re-submitting the same batch reuses existing samples/associations."""
        pid = _create_project(session)
        run_id = _create_run(session)

        payload = {
            "samples": [
                {"sample_id": "I001", "run_id": run_id},
                {"sample_id": "I002", "run_id": run_id},
            ]
        }

        # First submission
        r1 = client.post(
            f"/api/v1/projects/{pid}/samples/bulk", json=payload
        )
        assert r1.status_code == 201
        b1 = r1.json()
        assert b1["samples_created"] == 2
        assert b1["associations_created"] == 2

        # Second identical submission
        r2 = client.post(
            f"/api/v1/projects/{pid}/samples/bulk", json=payload
        )
        assert r2.status_code == 201
        b2 = r2.json()
        assert b2["samples_created"] == 0
        assert b2["samples_existing"] == 2
        assert b2["associations_created"] == 0
        assert b2["associations_existing"] == 2
        assert all(item["created"] is False for item in b2["items"])

        # UUIDs should match between submissions
        uuids1 = {
            i["sample_id"]: i["sample_uuid"] for i in b1["items"]
        }
        uuids2 = {
            i["sample_id"]: i["sample_uuid"] for i in b2["items"]
        }
        assert uuids1 == uuids2

    def test_bulk_partial_idempotency(
        self, client: TestClient, session: Session
    ):
        """Test that a batch correctly reports existing and newly created samples."""
        pid = _create_project(session)

        # Pre-create one sample
        client.post(
            f"/api/v1/projects/{pid}/samples",
            json={"sample_id": "P001"},
        )

        response = client.post(
            f"/api/v1/projects/{pid}/samples/bulk",
            json={
                "samples": [
                    {"sample_id": "P001"},  # already exists
                    {"sample_id": "P002"},  # new
                ]
            },
        )
        assert response.status_code == 201
        body = response.json()
        assert body["samples_created"] == 1
        assert body["samples_existing"] == 1

        items = {i["sample_id"]: i for i in body["items"]}
        assert items["P001"]["created"] is False
        assert items["P002"]["created"] is True

    # ----- Re-demux scenario -----

    def test_bulk_redemux_new_run_existing_samples(
        self, client: TestClient, session: Session
    ):
        """Test that existing samples get new run associations on re-demux."""
        pid = _create_project(session)
        run_id_1 = _create_run(session)
        run_id_2 = _create_second_run(session)

        # First submission on run 1
        r1 = client.post(
            f"/api/v1/projects/{pid}/samples/bulk",
            json={
                "samples": [
                    {"sample_id": "D001", "run_id": run_id_1},
                    {"sample_id": "D002", "run_id": run_id_1},
                ]
            },
        )
        assert r1.status_code == 201
        assert r1.json()["associations_created"] == 2

        # Second submission same samples, different run
        r2 = client.post(
            f"/api/v1/projects/{pid}/samples/bulk",
            json={
                "samples": [
                    {"sample_id": "D001", "run_id": run_id_2},
                    {"sample_id": "D002", "run_id": run_id_2},
                ]
            },
        )
        assert r2.status_code == 201
        b2 = r2.json()
        assert b2["samples_created"] == 0
        assert b2["samples_existing"] == 2
        assert b2["associations_created"] == 2  # new run associations
        assert b2["associations_existing"] == 0

        # Each sample should now have 2 run associations
        for sid in ("D001", "D002"):
            sample = session.exec(
                select(Sample).where(
                    Sample.sample_id == sid, Sample.project_id == pid
                )
            ).one()
            assocs = session.exec(
                select(SampleSequencingRun).where(
                    SampleSequencingRun.sample_id == sample.id
                )
            ).all()
            assert len(assocs) == 2

    # ----- Validation / error cases -----

    def test_bulk_empty_samples_list(
        self, client: TestClient, session: Session
    ):
        """Test that an empty samples list is rejected by the validator."""
        pid = _create_project(session)

        response = client.post(
            f"/api/v1/projects/{pid}/samples/bulk",
            json={"samples": []},
        )
        assert response.status_code == 422

    def test_bulk_duplicate_sample_ids_in_request(
        self, client: TestClient, session: Session
    ):
        """Test that duplicate sample_ids within a single request are rejected."""
        pid = _create_project(session)

        response = client.post(
            f"/api/v1/projects/{pid}/samples/bulk",
            json={
                "samples": [
                    {"sample_id": "DUP1"},
                    {"sample_id": "DUP1"},
                ]
            },
        )
        assert response.status_code == 422
        assert "duplicate" in response.json()["detail"].lower()

    def test_bulk_invalid_run_id(
        self, client: TestClient, session: Session
    ):
        """Test that an invalid run_id fails the entire batch (no partial commit)."""
        pid = _create_project(session)

        response = client.post(
            f"/api/v1/projects/{pid}/samples/bulk",
            json={
                "samples": [
                    {
                        "sample_id": "BAD1",
                        "run_id": "240101_XFAKE_0001_ZZZZZZZZZZ",
                    },
                ]
            },
        )
        assert response.status_code == 422
        assert "not found" in response.json()["detail"].lower()

        # No sample should have been created
        sample = session.exec(
            select(Sample).where(
                Sample.sample_id == "BAD1", Sample.project_id == pid
            )
        ).first()
        assert sample is None

    def test_bulk_mixed_valid_and_invalid_run_id_fails_all(
        self, client: TestClient, session: Session
    ):
        """Test that one bad run_id causes the whole batch to be rejected."""
        pid = _create_project(session)
        good_run_id = _create_run(session)

        response = client.post(
            f"/api/v1/projects/{pid}/samples/bulk",
            json={
                "samples": [
                    {"sample_id": "MIX1", "run_id": good_run_id},
                    {
                        "sample_id": "MIX2",
                        "run_id": "240101_XFAKE_0001_ZZZZZZZZZZ",
                    },
                ]
            },
        )
        assert response.status_code == 422

        # Neither sample should have been created
        for sid in ("MIX1", "MIX2"):
            s = session.exec(
                select(Sample).where(
                    Sample.sample_id == sid, Sample.project_id == pid
                )
            ).first()
            assert s is None

    def test_bulk_duplicate_attribute_keys_rejected(
        self, client: TestClient, session: Session
    ):
        """Test that duplicate attribute keys on a single sample are rejected."""
        pid = _create_project(session)

        response = client.post(
            f"/api/v1/projects/{pid}/samples/bulk",
            json={
                "samples": [
                    {
                        "sample_id": "ATTR1",
                        "attributes": [
                            {"key": "Tissue", "value": "Liver"},
                            {"key": "Tissue", "value": "Heart"},
                        ],
                    },
                ]
            },
        )
        assert response.status_code == 400
        assert "duplicate" in response.json()["detail"].lower()

    def test_bulk_nonexistent_project(
        self, client: TestClient, session: Session
    ):
        """Test that bulk endpoint against non-existent project returns 404."""
        response = client.post(
            "/api/v1/projects/P-NONEXISTENT-9999/samples/bulk",
            json={"samples": [{"sample_id": "X1"}]},
        )
        assert response.status_code == 404

    def test_bulk_extra_field_rejected(
        self, client: TestClient, session: Session
    ):
        """Test that extra fields in SampleCreate (model has extra='forbid') are rejected."""
        pid = _create_project(session)

        response = client.post(
            f"/api/v1/projects/{pid}/samples/bulk",
            json={
                "samples": [
                    {"sample_id": "E1", "unexpected_field": "boom"},
                ]
            },
        )
        assert response.status_code == 422

    def test_bulk_create_created_by_is_recorded(
        self, client: TestClient, session: Session
    ):
        """Test that created_by on SampleSequencingRun reflects the authenticated user."""
        pid = _create_project(session)
        run_id = _create_run(session)

        response = client.post(
            f"/api/v1/projects/{pid}/samples/bulk",
            json={
                "samples": [
                    {"sample_id": "CB1", "run_id": run_id},
                ]
            },
        )
        assert response.status_code == 201

        sample = session.exec(
            select(Sample).where(
                Sample.sample_id == "CB1", Sample.project_id == pid
            )
        ).one()
        assoc = session.exec(
            select(SampleSequencingRun).where(
                SampleSequencingRun.sample_id == sample.id
            )
        ).one()
        assert assoc.created_by == "testuser"

    def test_bulk_multiple_runs_in_same_batch(
        self, client: TestClient, session: Session
    ):
        """Test that samples in one batch can reference different runs."""
        pid = _create_project(session)
        run_id_1 = _create_run(session)
        run_id_2 = _create_second_run(session)

        response = client.post(
            f"/api/v1/projects/{pid}/samples/bulk",
            json={
                "samples": [
                    {"sample_id": "MR1", "run_id": run_id_1},
                    {"sample_id": "MR2", "run_id": run_id_2},
                    {"sample_id": "MR3"},
                ]
            },
        )
        assert response.status_code == 201
        body = response.json()
        assert body["samples_created"] == 3
        assert body["associations_created"] == 2

        items = {i["sample_id"]: i for i in body["items"]}
        assert items["MR1"]["run_id"] == run_id_1
        assert items["MR2"]["run_id"] == run_id_2
        assert items["MR3"]["run_id"] is None


# ===================================================================
# Bulk sample creation with inline files
# ===================================================================


class TestBulkSampleWithFiles:
    """POST /projects/{project_id}/samples/bulk with files."""

    def test_bulk_with_files_happy_path(
        self, client: TestClient, session: Session
    ):
        """Test that samples with files create File, FileSample, FileProject, tags, hashes."""
        pid = _create_project(session)

        response = client.post(
            f"/api/v1/projects/{pid}/samples/bulk",
            json={
                "samples": [
                    {
                        "sample_id": "F001",
                        "files": [
                            {
                                "uri": "s3://bucket/project/F001_R1.fastq.gz",
                                "tags": {"read": "R1", "format": "fastq.gz"},
                                "hashes": {"md5": "aaa111", "sha256": "bbb222"},
                                "role": "tumor",
                                "source": "pipeline-v1",
                            },
                            {
                                "uri": "s3://bucket/project/F001_R2.fastq.gz",
                                "tags": {"read": "R2"},
                            },
                        ],
                    },
                    {
                        "sample_id": "F002",
                        "files": [
                            {
                                "uri": "s3://bucket/project/F002_R1.fastq.gz",
                                "hashes": {"md5": "ccc333"},
                            },
                        ],
                    },
                ]
            },
        )
        assert response.status_code == 201
        body = response.json()
        assert body["samples_created"] == 2
        assert body["files_created"] == 3
        assert body["files_skipped"] == 0

        items = {i["sample_id"]: i for i in body["items"]}
        assert items["F001"]["files_created"] == 2
        assert items["F002"]["files_created"] == 1

        # Verify File records in DB
        sample_f001 = session.exec(
            select(Sample).where(
                Sample.sample_id == "F001", Sample.project_id == pid
            )
        ).one()

        file_samples = session.exec(
            select(FileSample).where(
                FileSample.sample_id == sample_f001.id
            )
        ).all()
        assert len(file_samples) == 2

        # Verify one of the files has correct tags and hashes
        r1_fs = [fs for fs in file_samples if fs.role == "tumor"]
        assert len(r1_fs) == 1
        r1_file = session.get(File, r1_fs[0].file_id)
        assert r1_file.uri == "s3://bucket/project/F001_R1.fastq.gz"
        assert r1_file.source == "pipeline-v1"

        # Check hashes
        hashes = session.exec(
            select(FileHash).where(FileHash.file_id == r1_file.id)
        ).all()
        hash_dict = {h.algorithm: h.value for h in hashes}
        assert hash_dict == {"md5": "aaa111", "sha256": "bbb222"}

        # Check tags
        tags = session.exec(
            select(FileTag).where(FileTag.file_id == r1_file.id)
        ).all()
        tag_dict = {t.key: t.value for t in tags}
        assert tag_dict == {"read": "R1", "format": "fastq.gz"}

        # Verify FileProject association
        project = session.exec(
            select(Project).where(Project.project_id == pid)
        ).one()
        file_projects = session.exec(
            select(FileProject).where(
                FileProject.file_id == r1_file.id
            )
        ).all()
        assert len(file_projects) == 1
        assert file_projects[0].project_id == project.id

    def test_bulk_idempotent_resubmission_no_hashes(
        self, client: TestClient, session: Session
    ):
        """Test that re-submitting same batch without hashes skips files, no duplicates."""
        pid = _create_project(session)

        payload = {
            "samples": [
                {
                    "sample_id": "ID001",
                    "files": [
                        {"uri": "s3://bucket/ID001_R1.fastq.gz"},
                        {"uri": "s3://bucket/ID001_R2.fastq.gz"},
                    ],
                },
            ]
        }

        # First submission
        r1 = client.post(
            f"/api/v1/projects/{pid}/samples/bulk", json=payload
        )
        assert r1.status_code == 201
        b1 = r1.json()
        assert b1["files_created"] == 2
        assert b1["files_skipped"] == 0

        # Second identical submission (no hashes → skip)
        r2 = client.post(
            f"/api/v1/projects/{pid}/samples/bulk", json=payload
        )
        assert r2.status_code == 201
        b2 = r2.json()
        assert b2["files_created"] == 0
        assert b2["files_skipped"] == 2

        # Verify only 2 File records exist for this sample
        sample = session.exec(
            select(Sample).where(
                Sample.sample_id == "ID001", Sample.project_id == pid
            )
        ).one()
        file_samples = session.exec(
            select(FileSample).where(FileSample.sample_id == sample.id)
        ).all()
        assert len(file_samples) == 2

    def test_bulk_idempotent_resubmission_matching_hashes(
        self, client: TestClient, session: Session
    ):
        """Test that re-submitting with matching hashes skips files."""
        pid = _create_project(session)

        payload = {
            "samples": [
                {
                    "sample_id": "IH001",
                    "files": [
                        {
                            "uri": "s3://bucket/IH001_R1.fastq.gz",
                            "hashes": {"md5": "match111"},
                        },
                    ],
                },
            ]
        }

        # First submission
        r1 = client.post(
            f"/api/v1/projects/{pid}/samples/bulk", json=payload
        )
        assert r1.status_code == 201
        assert r1.json()["files_created"] == 1

        # Second submission with same hash
        r2 = client.post(
            f"/api/v1/projects/{pid}/samples/bulk", json=payload
        )
        assert r2.status_code == 201
        b2 = r2.json()
        assert b2["files_created"] == 0
        assert b2["files_skipped"] == 1

    def test_hash_mismatch_creates_new_version(
        self, client: TestClient, session: Session
    ):
        """Test that same URI but different hash creates a new File version."""
        pid = _create_project(session)

        # First submission
        r1 = client.post(
            f"/api/v1/projects/{pid}/samples/bulk",
            json={
                "samples": [
                    {
                        "sample_id": "HM001",
                        "files": [
                            {
                                "uri": "s3://bucket/HM001_R1.fastq.gz",
                                "hashes": {"md5": "version1"},
                            },
                        ],
                    },
                ]
            },
        )
        assert r1.status_code == 201
        assert r1.json()["files_created"] == 1

        # Second submission with different hash for same URI
        r2 = client.post(
            f"/api/v1/projects/{pid}/samples/bulk",
            json={
                "samples": [
                    {
                        "sample_id": "HM001",
                        "files": [
                            {
                                "uri": "s3://bucket/HM001_R1.fastq.gz",
                                "hashes": {"md5": "version2"},
                            },
                        ],
                    },
                ]
            },
        )
        assert r2.status_code == 201
        b2 = r2.json()
        assert b2["files_created"] == 1
        assert b2["files_skipped"] == 0

        # Verify two File records with the same URI now exist
        sample = session.exec(
            select(Sample).where(
                Sample.sample_id == "HM001", Sample.project_id == pid
            )
        ).one()
        file_samples = session.exec(
            select(FileSample).where(FileSample.sample_id == sample.id)
        ).all()
        assert len(file_samples) == 2

        # Both should have the same URI
        file_ids = [fs.file_id for fs in file_samples]
        files = [session.get(File, fid) for fid in file_ids]
        uris = {f.uri for f in files}
        assert uris == {"s3://bucket/HM001_R1.fastq.gz"}

        # But different hashes
        all_hashes = set()
        for f in files:
            h = session.exec(
                select(FileHash).where(FileHash.file_id == f.id)
            ).all()
            for hh in h:
                all_hashes.add(hh.value)
        assert all_hashes == {"version1", "version2"}

    def test_bulk_mixed_samples_with_and_without_files(
        self, client: TestClient, session: Session
    ):
        """Test that some samples have files while others don't."""
        pid = _create_project(session)

        response = client.post(
            f"/api/v1/projects/{pid}/samples/bulk",
            json={
                "samples": [
                    {
                        "sample_id": "MF001",
                        "files": [
                            {"uri": "s3://bucket/MF001_R1.fastq.gz"},
                        ],
                    },
                    {
                        "sample_id": "MF002",
                        # No files
                    },
                    {
                        "sample_id": "MF003",
                        "files": [
                            {"uri": "s3://bucket/MF003_R1.fastq.gz"},
                            {"uri": "s3://bucket/MF003_R2.fastq.gz"},
                        ],
                    },
                ]
            },
        )
        assert response.status_code == 201
        body = response.json()
        assert body["samples_created"] == 3
        assert body["files_created"] == 3
        assert body["files_skipped"] == 0

        items = {i["sample_id"]: i for i in body["items"]}
        assert items["MF001"]["files_created"] == 1
        assert items["MF002"]["files_created"] == 0
        assert items["MF003"]["files_created"] == 2

    def test_bulk_no_files_field(
        self, client: TestClient, session: Session
    ):
        """Test that payloads without files field succeed with zero file counts."""
        pid = _create_project(session)

        response = client.post(
            f"/api/v1/projects/{pid}/samples/bulk",
            json={"samples": [{"sample_id": "BC001"}]},
        )
        assert response.status_code == 201
        body = response.json()
        assert body["files_created"] == 0
        assert body["files_skipped"] == 0
        assert body["items"][0]["files_created"] == 0
        assert body["items"][0]["files_skipped"] == 0


# ===================================================================
# Single-sample creation with inline files
# ===================================================================


class TestSingleSampleWithFiles:
    """POST /projects/{project_id}/samples with optional files."""

    def test_single_sample_with_files(
        self, client: TestClient, session: Session
    ):
        """Test that a single sample with files is created correctly."""
        pid = _create_project(session)

        response = client.post(
            f"/api/v1/projects/{pid}/samples",
            json={
                "sample_id": "SF001",
                "files": [
                    {
                        "uri": "s3://bucket/SF001_R1.fastq.gz",
                        "tags": {"read": "R1"},
                        "hashes": {"md5": "sf_hash_1"},
                        "role": "normal",
                    },
                ],
            },
        )
        assert response.status_code == 201
        body = response.json()
        assert body["sample_id"] == "SF001"
        # SamplePublic doesn't include file counts — that's by design

        # Verify files were created in the DB
        sample = session.exec(
            select(Sample).where(
                Sample.sample_id == "SF001", Sample.project_id == pid
            )
        ).one()
        file_samples = session.exec(
            select(FileSample).where(FileSample.sample_id == sample.id)
        ).all()
        assert len(file_samples) == 1
        assert file_samples[0].role == "normal"

        file_record = session.get(File, file_samples[0].file_id)
        assert file_record.uri == "s3://bucket/SF001_R1.fastq.gz"

        # Check hash
        hashes = session.exec(
            select(FileHash).where(
                FileHash.file_id == file_record.id
            )
        ).all()
        assert len(hashes) == 1
        assert hashes[0].algorithm == "md5"
        assert hashes[0].value == "sf_hash_1"

        # Check tag
        tags = session.exec(
            select(FileTag).where(FileTag.file_id == file_record.id)
        ).all()
        assert len(tags) == 1
        assert tags[0].key == "read"
        assert tags[0].value == "R1"

    def test_single_sample_file_dedup_no_hashes(
        self, client: TestClient, session: Session
    ):
        """Test that re-creating same sample+file (no hashes) silently skips."""
        pid = _create_project(session)

        # First: create via bulk (to get the sample + file)
        client.post(
            f"/api/v1/projects/{pid}/samples/bulk",
            json={
                "samples": [
                    {
                        "sample_id": "SD001",
                        "files": [
                            {"uri": "s3://bucket/SD001_R1.fastq.gz"},
                        ],
                    },
                ]
            },
        )

        # Second: re-submit the same file via bulk
        r2 = client.post(
            f"/api/v1/projects/{pid}/samples/bulk",
            json={
                "samples": [
                    {
                        "sample_id": "SD001",
                        "files": [
                            {"uri": "s3://bucket/SD001_R1.fastq.gz"},
                        ],
                    },
                ]
            },
        )
        assert r2.status_code == 201
        assert r2.json()["files_skipped"] == 1
        assert r2.json()["files_created"] == 0

        # Only 1 FileSample link should exist
        sample = session.exec(
            select(Sample).where(
                Sample.sample_id == "SD001", Sample.project_id == pid
            )
        ).one()
        file_samples = session.exec(
            select(FileSample).where(FileSample.sample_id == sample.id)
        ).all()
        assert len(file_samples) == 1

    def test_single_sample_without_files(
        self, client: TestClient, session: Session
    ):
        """Test that a sample is created successfully when files field is omitted."""
        pid = _create_project(session)

        response = client.post(
            f"/api/v1/projects/{pid}/samples",
            json={"sample_id": "NOFILE001"},
        )
        assert response.status_code == 201
        assert response.json()["sample_id"] == "NOFILE001"
