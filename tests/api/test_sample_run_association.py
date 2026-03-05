"""Tests for Sample ↔ SequencingRun association endpoints."""

from datetime import date, datetime, timezone

from fastapi.testclient import TestClient
from sqlmodel import Session, select

from api.project.models import Project
from api.project.services import generate_project_id
from api.runs.models import SequencingRun, SampleSequencingRun
from api.samples.models import Sample, SampleAttribute
from api.files.models import File, FileEntity, FileSample, FileHash, FileTag
from api.qcmetrics.models import QCMetric, QCMetricSample, QCRecord


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _create_run(session: Session) -> str:
    """Insert a sequencing run and return its barcode."""
    run = SequencingRun(
        run_date=date(2024, 3, 15),
        machine_id="M00001",
        run_number=42,
        flowcell_id="HXXXXXXXXX",
        experiment_name="TestExp",
    )
    session.add(run)
    session.commit()
    session.refresh(run)
    return run.barcode


def _create_sample(session: Session) -> str:
    """Insert a project + sample and return the sample id (UUID str)."""
    project = Project(name="Test Project")
    project.project_id = generate_project_id(session=session)
    project.attributes = []
    session.add(project)
    session.flush()

    sample = Sample(sample_id="SAMPLE_001", project_id=project.project_id)
    session.add(sample)
    session.commit()
    session.refresh(sample)
    return str(sample.id)


# ---------------------------------------------------------------------------
# POST /runs/{barcode}/samples
# ---------------------------------------------------------------------------

def test_associate_sample_with_run(client: TestClient, session: Session):
    """Associate a sample with a sequencing run."""
    barcode = _create_run(session)
    sample_id = _create_sample(session)

    resp = client.post(
        f"/api/v1/runs/{barcode}/samples",
        json={"sample_id": sample_id},
    )
    assert resp.status_code == 201
    data = resp.json()

    assert data["sample_id"] == sample_id
    assert data["created_by"] == "testuser"
    assert "id" in data
    assert "sequencing_run_id" in data
    assert "created_at" in data


def test_associate_sample_duplicate_conflict(client: TestClient, session: Session):
    """Associating the same sample twice returns 409."""
    barcode = _create_run(session)
    sample_id = _create_sample(session)

    resp1 = client.post(
        f"/api/v1/runs/{barcode}/samples",
        json={"sample_id": sample_id},
    )
    assert resp1.status_code == 201

    resp2 = client.post(
        f"/api/v1/runs/{barcode}/samples",
        json={"sample_id": sample_id},
    )
    assert resp2.status_code == 409


def test_associate_sample_run_not_found(client: TestClient, session: Session):
    """Associating with a non-existent run returns 404."""
    sample_id = _create_sample(session)
    resp = client.post(
        "/api/v1/runs/240101_NOEXIST_0001_FAKECELL/samples",
        json={"sample_id": sample_id},
    )
    assert resp.status_code == 404


def test_associate_sample_sample_not_found(client: TestClient, session: Session):
    """Associating a non-existent sample returns 404."""
    barcode = _create_run(session)
    fake_sample = "00000000-0000-0000-0000-000000000000"

    resp = client.post(
        f"/api/v1/runs/{barcode}/samples",
        json={"sample_id": fake_sample},
    )
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# GET /runs/{barcode}/samples
# ---------------------------------------------------------------------------

def test_get_samples_for_run_empty(client: TestClient, session: Session):
    """Listing samples for a run with no associations returns empty list."""
    barcode = _create_run(session)
    resp = client.get(f"/api/v1/runs/{barcode}/samples")
    assert resp.status_code == 200
    assert resp.json() == []


def test_get_samples_for_run(client: TestClient, session: Session):
    """List sample associations after adding one."""
    barcode = _create_run(session)
    sample_id = _create_sample(session)

    client.post(
        f"/api/v1/runs/{barcode}/samples",
        json={"sample_id": sample_id},
    )

    resp = client.get(f"/api/v1/runs/{barcode}/samples")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["sample_id"] == sample_id


def test_get_samples_for_run_not_found(client: TestClient):
    """Listing samples for a non-existent run returns 404."""
    resp = client.get("/api/v1/runs/240101_NOEXIST_0001_FAKECELL/samples")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# DELETE /runs/{barcode}/samples/{sample_id}
# ---------------------------------------------------------------------------

def test_remove_sample_from_run(client: TestClient, session: Session):
    """Remove a sample association from a run."""
    barcode = _create_run(session)
    sample_id = _create_sample(session)

    client.post(
        f"/api/v1/runs/{barcode}/samples",
        json={"sample_id": sample_id},
    )

    resp = client.delete(f"/api/v1/runs/{barcode}/samples/{sample_id}")
    assert resp.status_code == 204

    # Verify it's gone
    list_resp = client.get(f"/api/v1/runs/{barcode}/samples")
    assert list_resp.json() == []


def test_remove_sample_from_run_not_found(client: TestClient, session: Session):
    """Removing a non-associated sample returns 404."""
    barcode = _create_run(session)
    fake_sample = "00000000-0000-0000-0000-000000000000"

    resp = client.delete(f"/api/v1/runs/{barcode}/samples/{fake_sample}")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# DELETE /runs/{barcode}/samples  (bulk cleanup for re-demux)
# ---------------------------------------------------------------------------

def _create_second_run(session: Session) -> str:
    """Insert a second sequencing run and return its barcode."""
    run = SequencingRun(
        run_date=date(2024, 4, 20),
        machine_id="M00002",
        run_number=99,
        flowcell_id="HYYYYYYYYY",
        experiment_name="SecondExp",
    )
    session.add(run)
    session.commit()
    session.refresh(run)
    return run.barcode


def _associate(session: Session, sample_id: str, run_barcode: str) -> None:
    """Create a SampleSequencingRun association directly in the DB."""
    from uuid import UUID

    run = session.exec(
        select(SequencingRun).where(
            SequencingRun.run_date == SequencingRun.parse_barcode(run_barcode)[0],
            SequencingRun.machine_id == SequencingRun.parse_barcode(run_barcode)[2],
            SequencingRun.run_number == SequencingRun.parse_barcode(run_barcode)[3],
            SequencingRun.flowcell_id == SequencingRun.parse_barcode(run_barcode)[4],
        )
    ).one()
    assoc = SampleSequencingRun(
        sample_id=UUID(sample_id),
        sequencing_run_id=run.id,
        created_by="testuser",
    )
    session.add(assoc)
    session.commit()


def test_clear_samples_empty_run(client: TestClient, session: Session):
    """Clearing samples for a run with no associations returns zeros."""
    barcode = _create_run(session)
    resp = client.delete(f"/api/v1/runs/{barcode}/samples")
    assert resp.status_code == 200
    data = resp.json()
    assert data["run_barcode"] == barcode
    assert data["associations_removed"] == 0
    assert data["files_deleted"] == 0
    assert data["samples_deleted"] == 0
    assert data["samples_preserved"] == 0


def test_clear_samples_deletes_orphans(client: TestClient, session: Session):
    """Samples only associated with this run are deleted as orphans."""
    barcode = _create_run(session)
    sample_id = _create_sample(session)
    _associate(session, sample_id, barcode)

    # Verify sample exists
    from uuid import UUID
    assert session.get(Sample, UUID(sample_id)) is not None

    resp = client.delete(f"/api/v1/runs/{barcode}/samples")
    assert resp.status_code == 200
    data = resp.json()
    assert data["associations_removed"] == 1
    assert data["samples_deleted"] == 1
    assert data["samples_preserved"] == 0

    # Verify sample is gone
    assert session.get(Sample, UUID(sample_id)) is None

    # Verify association is gone
    assocs = session.exec(select(SampleSequencingRun)).all()
    assert len(assocs) == 0


def test_clear_samples_preserves_multi_run_sample(client: TestClient, session: Session):
    """A sample associated with another run is preserved."""
    barcode_a = _create_run(session)
    barcode_b = _create_second_run(session)
    sample_id = _create_sample(session)

    _associate(session, sample_id, barcode_a)
    _associate(session, sample_id, barcode_b)

    resp = client.delete(f"/api/v1/runs/{barcode_a}/samples")
    assert resp.status_code == 200
    data = resp.json()
    assert data["associations_removed"] == 1
    assert data["samples_deleted"] == 0
    assert data["samples_preserved"] == 1

    # Sample still exists
    from uuid import UUID
    assert session.get(Sample, UUID(sample_id)) is not None

    # Association with run_b still exists
    remaining = session.exec(
        select(SampleSequencingRun).where(
            SampleSequencingRun.sample_id == UUID(sample_id)
        )
    ).all()
    assert len(remaining) == 1


def test_clear_samples_preserves_sample_with_other_files(client: TestClient, session: Session):
    """A sample with file associations from another entity is preserved."""
    barcode = _create_run(session)
    sample_id = _create_sample(session)
    _associate(session, sample_id, barcode)

    from uuid import UUID

    # Create a file associated with a different entity (not this run)
    other_file = File(
        uri="s3://bucket/other/file.bam",
        created_on=datetime.now(timezone.utc),
    )
    session.add(other_file)
    session.flush()
    other_entity = FileEntity(
        file_id=other_file.id,
        entity_type="PROJECT",
        entity_id="P-99999",
    )
    session.add(other_entity)
    other_file_sample = FileSample(
        file_id=other_file.id,
        sample_id=UUID(sample_id),
    )
    session.add(other_file_sample)
    session.commit()

    resp = client.delete(f"/api/v1/runs/{barcode}/samples")
    assert resp.status_code == 200
    data = resp.json()
    assert data["samples_deleted"] == 0
    assert data["samples_preserved"] == 1

    # Sample still exists
    assert session.get(Sample, UUID(sample_id)) is not None


def test_clear_samples_preserves_sample_with_qc_data(client: TestClient, session: Session):
    """A sample with QC metric associations is preserved."""
    barcode = _create_run(session)
    sample_id = _create_sample(session)
    _associate(session, sample_id, barcode)

    from uuid import UUID

    # Create a QCRecord → QCMetric → QCMetricSample chain
    qcrecord = QCRecord(
        created_by="testuser",
        project_id="P-00001",
        created_on=datetime.now(timezone.utc),
    )
    session.add(qcrecord)
    session.flush()

    qcmetric = QCMetric(
        qcrecord_id=qcrecord.id,
        name="alignment_stats",
    )
    session.add(qcmetric)
    session.flush()

    qc_sample = QCMetricSample(
        qc_metric_id=qcmetric.id,
        sample_id=UUID(sample_id),
    )
    session.add(qc_sample)
    session.commit()

    resp = client.delete(f"/api/v1/runs/{barcode}/samples")
    assert resp.status_code == 200
    data = resp.json()
    assert data["samples_deleted"] == 0
    assert data["samples_preserved"] == 1

    # Sample still exists
    assert session.get(Sample, UUID(sample_id)) is not None


def test_clear_samples_deletes_run_files(client: TestClient, session: Session):
    """File records associated with the run via FileEntity are deleted."""
    barcode = _create_run(session)
    sample_id = _create_sample(session)
    _associate(session, sample_id, barcode)

    from uuid import UUID

    # Create files associated with this run
    file1 = File(
        uri=f"s3://bucket/runs/{barcode}/SampleA.fastq.gz",
        created_on=datetime.now(timezone.utc),
    )
    session.add(file1)
    session.flush()

    fe1 = FileEntity(file_id=file1.id, entity_type="RUN", entity_id=barcode)
    session.add(fe1)

    fh1 = FileHash(file_id=file1.id, algorithm="md5", value="abc123")
    session.add(fh1)

    ft1 = FileTag(file_id=file1.id, key="format", value="fastq")
    session.add(ft1)

    fs1 = FileSample(file_id=file1.id, sample_id=UUID(sample_id))
    session.add(fs1)

    file2 = File(
        uri=f"s3://bucket/runs/{barcode}/SampleA.bam",
        created_on=datetime.now(timezone.utc),
    )
    session.add(file2)
    session.flush()
    fe2 = FileEntity(file_id=file2.id, entity_type="RUN", entity_id=barcode)
    session.add(fe2)

    session.commit()

    # Verify files exist
    assert session.get(File, file1.id) is not None
    assert session.get(File, file2.id) is not None

    resp = client.delete(f"/api/v1/runs/{barcode}/samples")
    assert resp.status_code == 200
    data = resp.json()
    assert data["files_deleted"] == 2
    assert data["samples_deleted"] == 1  # sample is now orphaned (FileSample was cascaded)

    # Verify files are gone (cascade deleted hashes, tags, samples, entities too)
    assert session.get(File, file1.id) is None
    assert session.get(File, file2.id) is None

    # Verify cascaded children are gone
    assert session.exec(select(FileHash).where(FileHash.file_id == file1.id)).first() is None
    assert session.exec(select(FileTag).where(FileTag.file_id == file1.id)).first() is None
    assert session.exec(select(FileSample).where(FileSample.file_id == file1.id)).first() is None
    assert session.exec(select(FileEntity).where(FileEntity.file_id == file1.id)).first() is None


def test_clear_samples_deletes_sample_attributes(client: TestClient, session: Session):
    """SampleAttribute rows are deleted when their parent sample is orphaned."""
    barcode = _create_run(session)
    sample_id = _create_sample(session)
    _associate(session, sample_id, barcode)

    from uuid import UUID

    # Add attributes to the sample
    attr = SampleAttribute(sample_id=UUID(sample_id), key="tissue", value="blood")
    session.add(attr)
    session.commit()

    resp = client.delete(f"/api/v1/runs/{barcode}/samples")
    assert resp.status_code == 200
    assert resp.json()["samples_deleted"] == 1

    # Verify attributes are gone
    attrs = session.exec(
        select(SampleAttribute).where(SampleAttribute.sample_id == UUID(sample_id))
    ).all()
    assert len(attrs) == 0


def test_clear_samples_run_not_found(client: TestClient):
    """Clearing samples for a non-existent run returns 404."""
    resp = client.delete("/api/v1/runs/240101_NOEXIST_0001_FAKECELL/samples")
    assert resp.status_code == 404
