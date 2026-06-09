from sqlmodel import Session, select
from fastapi.testclient import TestClient

from api.project.models import Project
from api.samples.models import Sample, SampleAttribute
from api.files.models import File, FileSample, FileTag
from api.project.services import generate_project_id


def _create_project(session: Session, name: str = "Test Project") -> Project:
    """Helper function to create a project."""
    project = Project(name=name, created_by="testuser")
    project.project_id = generate_project_id(session=session)
    project.attributes = []
    session.add(project)
    session.commit()
    return project


def test_get_samples_for_a_project_with_no_samples(
    client: TestClient, session: Session
):
    """
    Test that we can get all samples for a project
    """
    # Add a project to the database
    new_project = _create_project(session)

    # Test No samples
    response = client.get(f"/api/v1/projects/{new_project.project_id}/samples")
    assert response.status_code == 200
    assert response.json() == {
        "data": [],
        "data_cols": None,
        "total_items": 0,
        "skip": 0,
        "limit": 100,
        "has_next": False,
        "has_prev": False,
    }


def test_get_samples_for_a_project_with_samples(client: TestClient, session: Session):
    """
    Test that we can get all samples for a project with samples
    """
    # Add a project to the database
    new_project_1 = _create_project(session, name="Test Project 1")

    # Add a second project
    new_project_2 = _create_project(session, name="Test Project 2")

    # Add sample 1
    sample_1 = Sample(sample_id="Sample_1", project_id=new_project_1.project_id)
    session.add(sample_1)
    session.flush()  # Flush to get the sample ID for attributes

    # Add attributes for Sample_1
    attr_1_1 = SampleAttribute(sample_id=sample_1.id, key="Tissue", value="Liver")
    attr_1_2 = SampleAttribute(sample_id=sample_1.id, key="Condition", value="Healthy")
    session.add(attr_1_1)
    session.add(attr_1_2)

    # Add sample 2
    sample_2 = Sample(sample_id="Sample_2", project_id=new_project_1.project_id)
    session.add(sample_2)
    session.flush()

    # Add attributes for Sample_2
    attr_2_1 = SampleAttribute(sample_id=sample_2.id, key="Tissue", value="Heart")
    attr_2_2 = SampleAttribute(sample_id=sample_2.id, key="Condition", value="Disease")
    session.add(attr_2_1)
    session.add(attr_2_2)

    # Add sample 3 to second project
    sample_3 = Sample(sample_id="Sample_3", project_id=new_project_2.project_id)
    session.add(sample_3)
    session.flush()

    # Add attributes for Sample_3
    attr_3_1 = SampleAttribute(sample_id=sample_3.id, key="Tissue", value="Brain")
    attr_3_2 = SampleAttribute(sample_id=sample_3.id, key="Condition", value="Healthy")
    session.add(attr_3_1)
    session.add(attr_3_2)

    session.commit()

    # Test with samples
    response = client.get(f"/api/v1/projects/{new_project_1.project_id}/samples")
    assert response.status_code == 200
    response_data = response.json()

    # Check that we have 2 samples
    assert len(response_data["data"]) == 2

    # Check that data_cols is present and contains the expected attribute keys
    assert "data_cols" in response_data
    assert response_data["data_cols"] is not None
    assert "Tissue" in response_data["data_cols"]
    assert "Condition" in response_data["data_cols"]

    # Without ?include=files, samples should NOT contain a 'files' key
    for sample in response_data["data"]:
        assert "files" not in sample

    # Check that attributes are present in the response for each sample
    for sample in response_data["data"]:
        assert "attributes" in sample
        assert sample["attributes"] is not None
        assert len(sample["attributes"]) == 2

        # Verify attribute structure
        attribute_keys = [attr["key"] for attr in sample["attributes"]]
        assert "Tissue" in attribute_keys
        assert "Condition" in attribute_keys

        # Verify specific sample attributes
        if sample["sample_id"] == "Sample_1":
            attrs = sample["attributes"]
            tissue_attr = next(attr for attr in attrs if attr["key"] == "Tissue")
            condition_attr = next(
                attr for attr in attrs if attr["key"] == "Condition"
            )
            assert tissue_attr["value"] == "Liver"
            assert condition_attr["value"] == "Healthy"
        elif sample["sample_id"] == "Sample_2":
            attrs = sample["attributes"]
            tissue_attr = next(attr for attr in attrs if attr["key"] == "Tissue")
            condition_attr = next(
                attr for attr in attrs if attr["key"] == "Condition"
            )
            assert tissue_attr["value"] == "Heart"
            assert condition_attr["value"] == "Disease"


def test_add_sample_to_project(client: TestClient, session: Session):
    """
    Test that we can add a sample to a project
    """
    # Add a project to the database
    new_project = _create_project(session, name="Test Project")

    # Add a sample to the project
    sample_data = {
        "sample_id": "Sample_1",
        "attributes": [
            {"key": "Tissue", "value": "Liver"},
            {"key": "Condition", "value": "Healthy"},
        ],
    }

    response = client.post(
        f"/api/v1/projects/{new_project.project_id}/samples", json=sample_data
    )
    assert response.status_code == 201
    assert response.json()["sample_id"] == "Sample_1"


def test_fail_to_add__sample_with_duplicate_attributes(
    client: TestClient, session: Session
):
    """
    Test that we properly fail to add a sample with duplicate keys.
    """
    # Add a project to the database
    new_project = _create_project(session, name="Test Project")

    # Add a sample to the project
    sample_data = {
        "sample_id": "Sample_1",
        "attributes": [
            {"key": "Tissue", "value": "Liver"},
            {"key": "Tissue", "value": "Heart"},
        ],
    }

    response = client.post(
        f"/api/v1/projects/{new_project.project_id}/samples", json=sample_data
    )
    assert response.status_code == 400


def test_fail_to_add_sample_with_case_insensitive_duplicate_attributes(
    client: TestClient, session: Session
):
    """Test that adding a sample with attribute keys differing only in case returns 400."""
    new_project = _create_project(session, name="Test Project")

    sample_data = {
        "sample_id": "Sample_1",
        "attributes": [
            {"key": "Tissue", "value": "Liver"},
            {"key": "tissue", "value": "Heart"},
        ],
    }

    response = client.post(
        f"/api/v1/projects/{new_project.project_id}/samples", json=sample_data
    )
    assert response.status_code == 400
    assert "duplicate" in response.json()["detail"].lower()


def test_fail_to_add_sample_to_project(client: TestClient, session: Session):
    """
    Test that we fail to add a sample to a project when a projecT_id is provided in sample data
    """
    # Add a project to the database
    new_project = _create_project(session, name="Test Project")

    # Add a sample to the project
    sample_data = {
        "sample_id": "Sample_1",
        "project_id": "a_project_id",
        "attributes": [
            {"key": "Tissue", "value": "Liver"},
            {"key": "Condition", "value": "Healthy"},
        ],
    }

    response = client.post(
        f"/api/v1/projects/{new_project.project_id}/samples", json=sample_data
    )
    assert response.status_code == 422
    assert "Extra inputs are not permitted" in response.json()["errors"][0]["message"]


def test_fail_to_add_sample_to_nonexistent_project(
    client: TestClient, session: Session
):
    """
    Test that we cannot add a sample to a non-existent project
    """
    # Attempt to add a sample to a non-existent project
    sample_data = {
        "sample_id": "Sample_1",
        "attributes": [
            {"key": "Tissue", "value": "Liver"},
            {"key": "Condition", "value": "Healthy"},
        ],
    }

    response = client.post(
        "/api/v1/projects/non_existent_project/samples", json=sample_data
    )
    assert response.status_code == 404


def test_add_samples_with_same_sampleid_to_different_projects(
    client: TestClient, session: Session
):
    """
    Test that we can add samples with the same sample_id to different projects
    """
    # Add two projects to the database
    new_project_1 = _create_project(session, name="Test Project 1")
    new_project_2 = _create_project(session, name="Test Project 2")

    session.commit()

    # Add a sample to the first project
    sample_data = {
        "sample_id": "Sample_1",
        "attributes": [
            {"key": "Tissue", "value": "Liver"},
            {"key": "Condition", "value": "Healthy"},
        ],
    }

    response = client.post(
        f"/api/v1/projects/{new_project_1.project_id}/samples", json=sample_data
    )
    assert response.status_code == 201
    assert response.json()["sample_id"] == "Sample_1"

    # Add a sample with the same sample_id to the second project
    sample_data = {
        "sample_id": "Sample_1",
        "attributes": [
            {"key": "Tissue", "value": "Breast"},
            {"key": "Condition", "value": "Healthy"},
        ],
    }
    response = client.post(
        f"/api/v1/projects/{new_project_2.project_id}/samples", json=sample_data
    )
    assert response.status_code == 201
    assert response.json()["sample_id"] == "Sample_1"


def test_update_sample_attribute(client: TestClient, session: Session):
    """
    Test that we can update a sample attribute
    """
    # Add a project to the database
    new_project = _create_project(session, name="Test Project")

    # Add a sample to the project
    sample_data = {
        "sample_id": "Sample_1",
        "attributes": [
            {"key": "Tissue", "value": "Liver"},
            {"key": "Condition", "value": "Healthy"},
        ],
    }

    response = client.post(
        f"/api/v1/projects/{new_project.project_id}/samples", json=sample_data
    )
    assert response.status_code == 201
    assert response.json()["sample_id"] == "Sample_1"

    # Update an attribute
    update_data = {"key": "Condition", "value": "Diseased"}
    response = client.put(
        f"/api/v1/projects/{new_project.project_id}/samples/Sample_1",
        json=update_data,
    )
    assert response.status_code == 200
    assert any(
        attr["key"] == "Condition" and attr["value"] == "Diseased"
        for attr in response.json()["attributes"]
    )


# ---------------------------------------------------------------------------
# ?include=files tests
# ---------------------------------------------------------------------------


def _seed_sample(session: Session, project: Project, name: str) -> Sample:
    """Create a sample in *project* and return it."""
    sample = Sample(sample_id=name, project_id=project.project_id)
    session.add(sample)
    session.flush()
    return sample


def _attach_file(
    session: Session,
    sample: Sample,
    uri: str,
    tags: dict | None = None,
    role: str | None = None,
) -> File:
    """Create a File, link it to *sample* via FileSample, optionally add tags."""
    file = File(uri=uri)
    session.add(file)
    session.flush()

    fs = FileSample(file_id=file.id, sample_id=sample.id, role=role)
    session.add(fs)

    if tags:
        for key, value in tags.items():
            session.add(FileTag(file_id=file.id, key=key, value=value))

    session.flush()
    return file


def test_get_samples_include_files_with_tagged_files(
    client: TestClient, session: Session
):
    """With ?include=files, samples that have files should return them with
    flat-dict tags."""
    project = _create_project(session, name="Include-Files Project")
    sample = _seed_sample(session, project, "SampleWithFastqs")

    _attach_file(
        session, sample,
        uri="s3://bucket/P-1234/SampleWithFastqs_1.fastq.gz",
        tags={"mate": "R1"},
    )
    _attach_file(
        session, sample,
        uri="s3://bucket/P-1234/SampleWithFastqs_2.fastq.gz",
        tags={"mate": "R2"},
    )
    session.commit()

    response = client.get(
        f"/api/v1/projects/{project.project_id}/samples",
        params={"include": "files"},
    )
    assert response.status_code == 200

    data = response.json()
    assert data["total_items"] == 1

    sample_item = data["data"][0]
    assert sample_item["sample_id"] == "SampleWithFastqs"
    assert sample_item["files"] is not None
    assert len(sample_item["files"]) == 2

    # Tags should be a flat dict, NOT a list of {key, value}
    uris = {f["uri"] for f in sample_item["files"]}
    assert "s3://bucket/P-1234/SampleWithFastqs_1.fastq.gz" in uris
    assert "s3://bucket/P-1234/SampleWithFastqs_2.fastq.gz" in uris

    for file_obj in sample_item["files"]:
        assert isinstance(file_obj["tags"], dict)
        assert "mate" in file_obj["tags"]
        assert file_obj["tags"]["mate"] in ("R1", "R2")


def test_get_samples_include_files_sample_with_no_files(
    client: TestClient, session: Session
):
    """A sample with no associated files should return ``files: null``."""
    project = _create_project(session, name="Include-Files Project")
    _seed_sample(session, project, "LonelySample")
    session.commit()

    response = client.get(
        f"/api/v1/projects/{project.project_id}/samples",
        params={"include": "files"},
    )
    assert response.status_code == 200

    sample_item = response.json()["data"][0]
    assert sample_item["files"] is None


def test_get_samples_include_files_with_untagged_files(
    client: TestClient, session: Session
):
    """A file with no tags should still appear; tags should be null."""
    project = _create_project(session, name="Include-Files Project")
    sample = _seed_sample(session, project, "SampleNoTags")
    _attach_file(session, sample, uri="s3://bucket/P-1234/SampleNoTags.bam")
    session.commit()

    response = client.get(
        f"/api/v1/projects/{project.project_id}/samples",
        params={"include": "files"},
    )
    assert response.status_code == 200

    sample_item = response.json()["data"][0]
    assert sample_item["files"] is not None
    assert len(sample_item["files"]) == 1
    assert sample_item["files"][0]["uri"] == "s3://bucket/P-1234/SampleNoTags.bam"
    # No tags → null (empty dict converted to None in model)
    assert sample_item["files"][0]["tags"] is None


def test_get_samples_include_files_pagination_works(
    client: TestClient, session: Session
):
    """Pagination should still work correctly when include=files."""
    project = _create_project(session, name="Include-Files Project")
    for i in range(5):
        s = _seed_sample(session, project, f"PaginatedSample_{i:02d}")
        _attach_file(
            session, s,
            uri=f"s3://bucket/P-1234/PaginatedSample_{i:02d}.bam",
            tags={"index": str(i)},
        )
    session.commit()

    # First page: skip=0, limit=2
    response = client.get(
        f"/api/v1/projects/{project.project_id}/samples",
        params={"include": "files", "limit": 2, "skip": 0},
    )
    assert response.status_code == 200

    data = response.json()
    assert data["total_items"] == 5
    assert data["limit"] == 2
    assert data["skip"] == 0
    assert data["has_next"] is True
    assert len(data["data"]) == 2

    # Every sample on the page should have files
    for sample_item in data["data"]:
        assert sample_item["files"] is not None
        assert len(sample_item["files"]) == 1

    # Last page: skip=4, limit=2 → 1 sample
    response = client.get(
        f"/api/v1/projects/{project.project_id}/samples",
        params={"include": "files", "limit": 2, "skip": 4},
    )
    assert response.status_code == 200

    data = response.json()
    assert len(data["data"]) == 1
    assert data["has_next"] is False
    assert data["has_prev"] is True


# ---------------------------------------------------------------------------
# Timestamp tests (created_at / updated_at)
# ---------------------------------------------------------------------------


def test_sample_created_at_set_on_creation(client: TestClient, session: Session):
    """Verify created_at is populated when a sample is created."""
    new_project = _create_project(session, name="Test Project")

    sample_data = {"sample_id": "TS_1", "attributes": [{"key": "k", "value": "v"}]}
    response = client.post(
        f"/api/v1/projects/{new_project.project_id}/samples", json=sample_data
    )
    assert response.status_code == 201

    # Verify in DB
    sample = session.exec(select(Sample).where(Sample.sample_id == "TS_1")).first()
    assert sample.created_at is not None
    assert sample.updated_at is None


def test_sample_updated_at_set_on_update(client: TestClient, session: Session):
    """Verify updated_at is populated when a sample attribute is modified."""
    new_project = _create_project(session, name="Test Project")

    sample_data = {"sample_id": "TS_2", "attributes": [{"key": "k", "value": "v"}]}
    client.post(
        f"/api/v1/projects/{new_project.project_id}/samples", json=sample_data
    )

    # Update attribute
    update_data = {"key": "k", "value": "v2"}
    response = client.put(
        f"/api/v1/projects/{new_project.project_id}/samples/TS_2",
        json=update_data,
    )
    assert response.status_code == 200

    # Verify in DB
    session.expire_all()
    sample = session.exec(select(Sample).where(Sample.sample_id == "TS_2")).first()
    assert sample.updated_at is not None


def test_get_samples_include_files_mixed_samples(
    client: TestClient, session: Session
):
    """A project with a mix of samples (with and without files) returns the
    correct shape for each."""
    project = _create_project(session, name="Include-Files Project")

    # Sample with files
    s1 = _seed_sample(session, project, "SampleWithFiles")
    _attach_file(session, s1, uri="s3://bucket/file1.fastq.gz", tags={"mate": "R1"})

    # Sample without files
    _seed_sample(session, project, "SampleWithNoFiles")
    session.commit()

    response = client.get(
        f"/api/v1/projects/{project.project_id}/samples",
        params={"include": "files"},
    )
    assert response.status_code == 200

    items = {s["sample_id"]: s for s in response.json()["data"]}
    assert items["SampleWithFiles"]["files"] is not None
    assert len(items["SampleWithFiles"]["files"]) == 1
    assert items["SampleWithNoFiles"]["files"] is None


# ---------------------------------------------------------------------------
# file_versions deduplication tests
# ---------------------------------------------------------------------------


def test_get_samples_file_versions_latest_deduplicates(
    client: TestClient, session: Session
):
    """With file_versions=latest (default), only the newest version of each
    URI should be returned per sample."""
    from datetime import datetime, timezone

    project = _create_project(session, name="Include-Files Project")
    sample = _seed_sample(session, project, "SampleDedupLatest")

    uri = "s3://bucket/P-1234/SampleDedupLatest_R1.fastq.gz"

    # Create older version
    older_file = File(
        uri=uri,
        created_on=datetime(2024, 1, 1, tzinfo=timezone.utc),
    )
    session.add(older_file)
    session.flush()
    session.add(FileSample(file_id=older_file.id, sample_id=sample.id))
    session.add(FileTag(file_id=older_file.id, key="mate", value="R1"))
    session.add(FileTag(file_id=older_file.id, key="version", value="old"))

    # Create newer version (same URI, later timestamp)
    newer_file = File(
        uri=uri,
        created_on=datetime(2024, 6, 15, tzinfo=timezone.utc),
    )
    session.add(newer_file)
    session.flush()
    session.add(FileSample(file_id=newer_file.id, sample_id=sample.id))
    session.add(FileTag(file_id=newer_file.id, key="mate", value="R1"))
    session.add(FileTag(file_id=newer_file.id, key="version", value="new"))

    session.commit()

    # Default (file_versions=latest) — should return only 1 file
    response = client.get(
        f"/api/v1/projects/{project.project_id}/samples",
        params={"include": "files"},
    )
    assert response.status_code == 200
    data = response.json()["data"]
    assert len(data) == 1

    files = data[0]["files"]
    assert files is not None
    assert len(files) == 1
    assert files[0]["uri"] == uri
    # Should be the newer version's tags
    assert files[0]["tags"]["version"] == "new"
    # Should include created_on from the newer version
    assert "created_on" in files[0]
    assert files[0]["created_on"] == "2024-06-15T00:00:00Z"


def test_get_samples_file_versions_all_returns_all(
    client: TestClient, session: Session
):
    """With file_versions=all, all versions of each URI should be returned."""
    from datetime import datetime, timezone

    project = _create_project(session, name="Include-Files Project")
    sample = _seed_sample(session, project, "SampleDedupAll")

    uri = "s3://bucket/P-1234/SampleDedupAll_R1.fastq.gz"

    # Create older version
    older_file = File(
        uri=uri,
        created_on=datetime(2024, 1, 1, tzinfo=timezone.utc),
    )
    session.add(older_file)
    session.flush()
    session.add(FileSample(file_id=older_file.id, sample_id=sample.id))
    session.add(FileTag(file_id=older_file.id, key="mate", value="R1"))

    # Create newer version
    newer_file = File(
        uri=uri,
        created_on=datetime(2024, 6, 15, tzinfo=timezone.utc),
    )
    session.add(newer_file)
    session.flush()
    session.add(FileSample(file_id=newer_file.id, sample_id=sample.id))
    session.add(FileTag(file_id=newer_file.id, key="mate", value="R1"))

    session.commit()

    # file_versions=all — should return both versions
    response = client.get(
        f"/api/v1/projects/{project.project_id}/samples",
        params={"include": "files", "file_versions": "all"},
    )
    assert response.status_code == 200
    data = response.json()["data"]
    assert len(data) == 1

    files = data[0]["files"]
    assert files is not None
    assert len(files) == 2
    # Both should have the same URI
    assert all(f["uri"] == uri for f in files)


def test_get_samples_file_versions_latest_distinct_uris_preserved(
    client: TestClient, session: Session
):
    """Deduplication only collapses same-URI files; distinct URIs are kept."""
    from datetime import datetime, timezone

    project = _create_project(session, name="Include-Files Project")
    sample = _seed_sample(session, project, "SampleDistinctURIs")

    uri_r1 = "s3://bucket/P-1234/SampleDistinctURIs_R1.fastq.gz"
    uri_r2 = "s3://bucket/P-1234/SampleDistinctURIs_R2.fastq.gz"

    # R1 file (two versions)
    f1_old = File(uri=uri_r1, created_on=datetime(2024, 1, 1, tzinfo=timezone.utc))
    session.add(f1_old)
    session.flush()
    session.add(FileSample(file_id=f1_old.id, sample_id=sample.id))
    session.add(FileTag(file_id=f1_old.id, key="mate", value="R1"))

    f1_new = File(uri=uri_r1, created_on=datetime(2024, 6, 1, tzinfo=timezone.utc))
    session.add(f1_new)
    session.flush()
    session.add(FileSample(file_id=f1_new.id, sample_id=sample.id))
    session.add(FileTag(file_id=f1_new.id, key="mate", value="R1"))

    # R2 file (single version)
    f2 = File(uri=uri_r2, created_on=datetime(2024, 3, 1, tzinfo=timezone.utc))
    session.add(f2)
    session.flush()
    session.add(FileSample(file_id=f2.id, sample_id=sample.id))
    session.add(FileTag(file_id=f2.id, key="mate", value="R2"))

    session.commit()

    # Default (latest) — should return 2 files (one per URI)
    response = client.get(
        f"/api/v1/projects/{project.project_id}/samples",
        params={"include": "files"},
    )
    assert response.status_code == 200
    data = response.json()["data"]
    assert len(data) == 1

    files = data[0]["files"]
    assert files is not None
    assert len(files) == 2

    uris = {f["uri"] for f in files}
    assert uri_r1 in uris
    assert uri_r2 in uris


def test_get_samples_file_versions_without_include_files_ignored(
    client: TestClient, session: Session
):
    """file_versions param has no effect when include=files is not specified."""
    project = _create_project(session, name="Include-Files Project")
    _seed_sample(session, project, "SampleNoInclude")
    session.commit()

    response = client.get(
        f"/api/v1/projects/{project.project_id}/samples",
        params={"file_versions": "all"},
    )
    assert response.status_code == 200
    data = response.json()["data"]
    assert len(data) == 1
    # Should not have a 'files' key in the response
    assert "files" not in data[0]
