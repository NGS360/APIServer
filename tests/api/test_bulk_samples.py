"""Tests for single-sample run_barcode enrichment and bulk sample creation endpoint."""

from datetime import date

from fastapi.testclient import TestClient
from sqlmodel import Session, select

from api.project.models import Project
from api.project.services import generate_project_id
from api.runs.models import SequencingRun, SampleSequencingRun
from api.samples.models import Sample, SampleAttribute


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
    run_date: date = date(2024, 3, 15),
    machine_id: str = "M00001",
    run_number: int = 42,
    flowcell_id: str = "HXXXXXXXXX",
    experiment_name: str = "TestExp",
) -> str:
    """Insert a sequencing run and return its barcode."""
    run = SequencingRun(
        run_date=run_date,
        machine_id=machine_id,
        run_number=run_number,
        flowcell_id=flowcell_id,
        experiment_name=experiment_name,
    )
    session.add(run)
    session.commit()
    session.refresh(run)
    return run.barcode  # e.g. "240315_M00001_0042_HXXXXXXXXX"


def _create_second_run(session: Session) -> str:
    """Insert a second, distinct sequencing run."""
    return _create_run(
        session,
        run_date=date(2024, 4, 20),
        machine_id="M00002",
        run_number=99,
        flowcell_id="JYYYYYYYYY",
        experiment_name="TestExp2",
    )


# ===================================================================
# Single-sample endpoint with run_barcode
# ===================================================================


class TestSingleSampleWithRunBarcode:
    """POST /projects/{project_id}/samples with optional run_barcode."""

    def test_create_sample_with_run_barcode(
        self, client: TestClient, session: Session
    ):
        """Happy path: sample + SampleSequencingRun created in one call."""
        pid = _create_project(session)
        barcode = _create_run(session)

        response = client.post(
            f"/api/v1/projects/{pid}/samples",
            json={
                "sample_id": "S001",
                "run_barcode": barcode,
                "attributes": [{"key": "Tissue", "value": "Liver"}],
            },
        )
        assert response.status_code == 201
        body = response.json()
        assert body["sample_id"] == "S001"
        assert body["project_id"] == pid
        assert body["run_barcode"] == barcode

        # Verify the association was persisted
        sample = session.exec(
            select(Sample).where(Sample.sample_id == "S001", Sample.project_id == pid)
        ).one()
        assoc = session.exec(
            select(SampleSequencingRun).where(
                SampleSequencingRun.sample_id == sample.id
            )
        ).first()
        assert assoc is not None
        assert assoc.created_by == "testuser"

    def test_create_sample_without_run_barcode_backward_compat(
        self, client: TestClient, session: Session
    ):
        """Omitting run_barcode still works as before."""
        pid = _create_project(session)

        response = client.post(
            f"/api/v1/projects/{pid}/samples",
            json={"sample_id": "S002"},
        )
        assert response.status_code == 201
        body = response.json()
        assert body["sample_id"] == "S002"
        assert body["run_barcode"] is None

        # No association created
        sample = session.exec(
            select(Sample).where(Sample.sample_id == "S002", Sample.project_id == pid)
        ).one()
        assocs = session.exec(
            select(SampleSequencingRun).where(
                SampleSequencingRun.sample_id == sample.id
            )
        ).all()
        assert len(assocs) == 0

    def test_create_sample_with_invalid_run_barcode(
        self, client: TestClient, session: Session
    ):
        """Invalid barcode returns 404; no sample is created."""
        pid = _create_project(session)

        response = client.post(
            f"/api/v1/projects/{pid}/samples",
            json={"sample_id": "S003", "run_barcode": "240101_XFAKE_0001_ZZZZZZZZZZ"},
        )
        assert response.status_code == 404
        assert "not found" in response.json()["detail"].lower()

        # Sample should NOT have been created
        sample = session.exec(
            select(Sample).where(Sample.sample_id == "S003", Sample.project_id == pid)
        ).first()
        assert sample is None

    def test_create_sample_with_null_run_barcode(
        self, client: TestClient, session: Session
    ):
        """Explicitly passing null run_barcode is the same as omitting it."""
        pid = _create_project(session)

        response = client.post(
            f"/api/v1/projects/{pid}/samples",
            json={"sample_id": "S004", "run_barcode": None},
        )
        assert response.status_code == 201
        assert response.json()["run_barcode"] is None


# ===================================================================
# Bulk sample creation endpoint
# ===================================================================


class TestBulkSampleCreation:
    """POST /projects/{project_id}/samples/bulk."""

    # ----- Happy-path / basic -----

    def test_bulk_create_basic(self, client: TestClient, session: Session):
        """Create multiple samples without run associations."""
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

    def test_bulk_create_with_run_barcode(
        self, client: TestClient, session: Session
    ):
        """All samples associated with a run in one call."""
        pid = _create_project(session)
        barcode = _create_run(session)

        response = client.post(
            f"/api/v1/projects/{pid}/samples/bulk",
            json={
                "samples": [
                    {"sample_id": "R001", "run_barcode": barcode},
                    {"sample_id": "R002", "run_barcode": barcode},
                ]
            },
        )
        assert response.status_code == 201
        body = response.json()
        assert body["samples_created"] == 2
        assert body["associations_created"] == 2
        for item in body["items"]:
            assert item["run_barcode"] == barcode

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
        """Attributes are persisted for each sample in the batch."""
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
            select(SampleAttribute).where(SampleAttribute.sample_id == s1.id)
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
            select(SampleAttribute).where(SampleAttribute.sample_id == s2.id)
        ).all()
        assert len(attrs2) == 1
        assert attrs2[0].key == "Tissue"
        assert attrs2[0].value == "Heart"

    def test_bulk_create_mixed_with_and_without_run(
        self, client: TestClient, session: Session
    ):
        """Some samples have run_barcode, some don't."""
        pid = _create_project(session)
        barcode = _create_run(session)

        response = client.post(
            f"/api/v1/projects/{pid}/samples/bulk",
            json={
                "samples": [
                    {"sample_id": "M001", "run_barcode": barcode},
                    {"sample_id": "M002"},
                    {"sample_id": "M003", "run_barcode": barcode},
                ]
            },
        )
        assert response.status_code == 201
        body = response.json()
        assert body["samples_created"] == 3
        assert body["associations_created"] == 2

        items = {i["sample_id"]: i for i in body["items"]}
        assert items["M001"]["run_barcode"] == barcode
        assert items["M002"]["run_barcode"] is None
        assert items["M003"]["run_barcode"] == barcode

    # ----- Idempotency -----

    def test_bulk_idempotent_resubmission(
        self, client: TestClient, session: Session
    ):
        """Re-submitting the same batch reuses existing samples/associations."""
        pid = _create_project(session)
        barcode = _create_run(session)

        payload = {
            "samples": [
                {"sample_id": "I001", "run_barcode": barcode},
                {"sample_id": "I002", "run_barcode": barcode},
            ]
        }

        # First submission
        r1 = client.post(f"/api/v1/projects/{pid}/samples/bulk", json=payload)
        assert r1.status_code == 201
        b1 = r1.json()
        assert b1["samples_created"] == 2
        assert b1["associations_created"] == 2

        # Second identical submission
        r2 = client.post(f"/api/v1/projects/{pid}/samples/bulk", json=payload)
        assert r2.status_code == 201
        b2 = r2.json()
        assert b2["samples_created"] == 0
        assert b2["samples_existing"] == 2
        assert b2["associations_created"] == 0
        assert b2["associations_existing"] == 2
        assert all(item["created"] is False for item in b2["items"])

        # UUIDs should match between submissions
        uuids1 = {i["sample_id"]: i["sample_uuid"] for i in b1["items"]}
        uuids2 = {i["sample_id"]: i["sample_uuid"] for i in b2["items"]}
        assert uuids1 == uuids2

    def test_bulk_partial_idempotency(
        self, client: TestClient, session: Session
    ):
        """Batch with some existing and some new samples."""
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
        """Samples already exist; new run association is added (re-demux)."""
        pid = _create_project(session)
        barcode1 = _create_run(session)
        barcode2 = _create_second_run(session)

        # First submission on run 1
        r1 = client.post(
            f"/api/v1/projects/{pid}/samples/bulk",
            json={
                "samples": [
                    {"sample_id": "D001", "run_barcode": barcode1},
                    {"sample_id": "D002", "run_barcode": barcode1},
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
                    {"sample_id": "D001", "run_barcode": barcode2},
                    {"sample_id": "D002", "run_barcode": barcode2},
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
        """Empty samples list is rejected by the validator."""
        pid = _create_project(session)

        response = client.post(
            f"/api/v1/projects/{pid}/samples/bulk",
            json={"samples": []},
        )
        assert response.status_code == 422

    def test_bulk_duplicate_sample_ids_in_request(
        self, client: TestClient, session: Session
    ):
        """Duplicate sample_ids within a single request are rejected."""
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

    def test_bulk_invalid_run_barcode(
        self, client: TestClient, session: Session
    ):
        """Invalid run barcode fails the entire batch (no partial commit)."""
        pid = _create_project(session)

        response = client.post(
            f"/api/v1/projects/{pid}/samples/bulk",
            json={
                "samples": [
                    {"sample_id": "BAD1", "run_barcode": "240101_XFAKE_0001_ZZZZZZZZZZ"},
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

    def test_bulk_mixed_valid_and_invalid_barcode_fails_all(
        self, client: TestClient, session: Session
    ):
        """One bad barcode causes the whole batch to be rejected."""
        pid = _create_project(session)
        good_barcode = _create_run(session)

        response = client.post(
            f"/api/v1/projects/{pid}/samples/bulk",
            json={
                "samples": [
                    {"sample_id": "MIX1", "run_barcode": good_barcode},
                    {"sample_id": "MIX2", "run_barcode": "240101_XFAKE_0001_ZZZZZZZZZZ"},
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
        """Duplicate attribute keys on a single sample are rejected."""
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

    def test_bulk_nonexistent_project(self, client: TestClient, session: Session):
        """Bulk endpoint against non-existent project returns 404."""
        response = client.post(
            "/api/v1/projects/P-NONEXISTENT-9999/samples/bulk",
            json={"samples": [{"sample_id": "X1"}]},
        )
        assert response.status_code == 404

    def test_bulk_extra_field_rejected(
        self, client: TestClient, session: Session
    ):
        """Extra fields in SampleCreate (model has extra='forbid') are rejected."""
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
        """created_by on SampleSequencingRun reflects the authenticated user."""
        pid = _create_project(session)
        barcode = _create_run(session)

        response = client.post(
            f"/api/v1/projects/{pid}/samples/bulk",
            json={
                "samples": [
                    {"sample_id": "CB1", "run_barcode": barcode},
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
        """Samples in one batch can reference different runs."""
        pid = _create_project(session)
        barcode1 = _create_run(session)
        barcode2 = _create_second_run(session)

        response = client.post(
            f"/api/v1/projects/{pid}/samples/bulk",
            json={
                "samples": [
                    {"sample_id": "MR1", "run_barcode": barcode1},
                    {"sample_id": "MR2", "run_barcode": barcode2},
                    {"sample_id": "MR3"},
                ]
            },
        )
        assert response.status_code == 201
        body = response.json()
        assert body["samples_created"] == 3
        assert body["associations_created"] == 2

        items = {i["sample_id"]: i for i in body["items"]}
        assert items["MR1"]["run_barcode"] == barcode1
        assert items["MR2"]["run_barcode"] == barcode2
        assert items["MR3"]["run_barcode"] is None
