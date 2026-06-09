"""
Tests for v1 /api/v1/samples/search endpoints.

These tests verify that structured filtering works with v1 response format
(SamplesPublic) instead of legacy format (LegacySampleSearchResponse).
"""

from sqlmodel import Session
from fastapi.testclient import TestClient
from datetime import datetime, timezone

from api.project.models import Project
from api.samples.models import Sample, SampleAttribute
from api.project.services import generate_project_id


def _create_project(session: Session, name: str = "Test Project") -> Project:
    """Helper to create a project."""
    project = Project(name=name)
    project.project_id = generate_project_id(session=session)
    project.attributes = []
    session.add(project)
    session.flush()
    return project


def _create_sample(
    session: Session,
    project: Project,
    sample_id: str,
    attributes: dict | None = None,
    created_at: datetime | None = None,
) -> Sample:
    """Helper to create a sample with optional attributes."""
    sample = Sample(
        sample_id=sample_id,
        project_id=project.project_id,
        created_at=created_at or datetime.now(timezone.utc),
    )
    session.add(sample)
    session.flush()

    if attributes:
        for key, value in attributes.items():
            attr = SampleAttribute(sample_id=sample.id, key=key, value=value)
            session.add(attr)

    session.flush()
    return sample


# ──────────────────────────────────────────────────────────────────
# GET /api/v1/samples/search
# ──────────────────────────────────────────────────────────────────


class TestV1GetSearch:
    """Tests for GET /api/v1/samples/search"""

    def test_search_by_projectid(self, client: TestClient, session: Session):
        """Search by projectid returns matching samples in v1 format."""
        project = _create_project(session)
        _create_sample(session, project, "S1", {"Tissue": "Liver"})
        _create_sample(session, project, "S2", {"Tissue": "Heart"})
        session.commit()

        response = client.get(
            "/api/v1/samples/search",
            params={"projectid": project.project_id},
        )
        assert response.status_code == 200
        data = response.json()

        # V1 response format
        assert data["total_items"] == 2
        assert len(data["data"]) == 2
        assert "current_page" in data
        assert "per_page" in data
        assert "has_next" in data
        assert "has_prev" in data

        # Each sample has v1 shape
        for sample in data["data"]:
            assert "sample_id" in sample
            assert "project_id" in sample
            assert "attributes" in sample
            assert sample["project_id"] == project.project_id

    def test_search_by_samplename(self, client: TestClient, session: Session):
        """Search by samplename returns the matching sample."""
        project = _create_project(session)
        _create_sample(session, project, "MySample", {"Tissue": "Liver"})
        _create_sample(session, project, "Other", {"Tissue": "Heart"})
        session.commit()

        response = client.get(
            "/api/v1/samples/search",
            params={"samplename": "MySample"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["total_items"] == 1
        assert data["data"][0]["sample_id"] == "MySample"

    def test_combined_search(self, client: TestClient, session: Session):
        """Combined projectid + samplename returns intersection."""
        p1 = _create_project(session, "P1")
        p2 = _create_project(session, "P2")
        _create_sample(session, p1, "SharedName")
        _create_sample(session, p2, "SharedName")
        session.commit()

        response = client.get(
            "/api/v1/samples/search",
            params={"projectid": p1.project_id, "samplename": "SharedName"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["total_items"] == 1
        assert data["data"][0]["project_id"] == p1.project_id

    def test_search_by_attribute_as_query_param(
        self, client: TestClient, session: Session
    ):
        """Unknown query params are searched as attributes (case-insensitive key)."""
        project = _create_project(session)
        _create_sample(session, project, "S1", {"ASSAY_METHOD": "RNA-Seq"})
        _create_sample(session, project, "S2", {"ASSAY_METHOD": "WES"})
        session.commit()

        # lowercase key should match uppercase attribute
        response = client.get(
            "/api/v1/samples/search",
            params={"assay_method": "RNA-Seq"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["total_items"] == 1
        assert data["data"][0]["sample_id"] == "S1"

    def test_search_by_created_at(self, client: TestClient, session: Session):
        """Search by created_at matches date prefix of created_at."""
        project = _create_project(session)
        _create_sample(
            session, project, "S1",
            created_at=datetime(2026, 1, 21, 10, 30, 0, tzinfo=timezone.utc),
        )
        _create_sample(
            session, project, "S2",
            created_at=datetime(2026, 1, 22, 10, 30, 0, tzinfo=timezone.utc),
        )
        session.commit()

        response = client.get(
            "/api/v1/samples/search",
            params={"created_at": "2026-01-21"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["total_items"] == 1
        assert data["data"][0]["sample_id"] == "S1"
        # created_at is surfaced in the response (date prefix matches the filter)
        assert data["data"][0]["created_at"].startswith("2026-01-21")

    def test_search_by_created_at_iso_datetime(
        self, client: TestClient, session: Session
    ):
        """created_at accepts a full ISO datetime and matches on its date part."""
        project = _create_project(session)
        _create_sample(
            session, project, "S1",
            created_at=datetime(2026, 1, 21, 10, 30, 0, tzinfo=timezone.utc),
        )
        session.commit()

        response = client.get(
            "/api/v1/samples/search",
            params={"created_at": "2026-01-21T10:30:00"},
        )
        assert response.status_code == 200
        assert response.json()["total_items"] == 1

    def test_search_by_created_at_invalid_format(
        self, client: TestClient, session: Session
    ):
        """Malformed created_at returns 400, not a silent unfiltered dump.

        Regression: a trailing 'T' (or any unparseable value) used to be caught
        and the filter silently dropped, returning every sample in the project.
        """
        project = _create_project(session)
        _create_sample(session, project, "S1")
        _create_sample(session, project, "S2")
        session.commit()

        response = client.get(
            "/api/v1/samples/search",
            params={"projectid": project.project_id, "created_at": "2024-09-13T"},
        )
        assert response.status_code == 400

    def test_empty_results(self, client: TestClient, session: Session):
        """Non-matching query returns empty results."""
        project = _create_project(session)
        _create_sample(session, project, "S1")
        session.commit()

        response = client.get(
            "/api/v1/samples/search",
            params={"projectid": "nonexistent"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["total_items"] == 0
        assert data["data"] == []

    def test_no_params_returns_all(self, client: TestClient, session: Session):
        """GET with no params returns all samples."""
        project = _create_project(session)
        _create_sample(session, project, "S1")
        _create_sample(session, project, "S2")
        session.commit()

        response = client.get("/api/v1/samples/search")
        assert response.status_code == 200
        assert response.json()["total_items"] == 2

    def test_get_pagination(self, client: TestClient, session: Session):
        """GET with page and per_page returns paginated results."""
        project = _create_project(session)
        for i in range(5):
            _create_sample(session, project, f"S{i}")
        session.commit()

        # Page 1, per_page=2
        response = client.get(
            "/api/v1/samples/search",
            params={"projectid": project.project_id, "page": 1, "per_page": 2},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["total_items"] == 5
        assert data["current_page"] == 1
        assert data["per_page"] == 2
        assert len(data["data"]) == 2
        assert data["has_next"] is True
        assert data["has_prev"] is False

        # Page 3, per_page=2 — should get 1 result
        response = client.get(
            "/api/v1/samples/search",
            params={"projectid": project.project_id, "page": 3, "per_page": 2},
        )
        data = response.json()
        assert data["total_items"] == 5
        assert len(data["data"]) == 1
        assert data["has_next"] is False
        assert data["has_prev"] is True

    def test_data_cols_populated(self, client: TestClient, session: Session):
        """Verify data_cols is populated from matching samples' attributes."""
        project = _create_project(session)
        _create_sample(session, project, "S1", {"Tissue": "Liver", "Method": "RNA-Seq"})
        _create_sample(session, project, "S2", {"Tissue": "Heart"})
        session.commit()

        response = client.get(
            "/api/v1/samples/search",
            params={"projectid": project.project_id},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["data_cols"] is not None
        assert "Tissue" in data["data_cols"]
        assert "Method" in data["data_cols"]

    def test_attributes_in_v1_format(self, client: TestClient, session: Session):
        """Verify attributes are returned as list of {key, value} dicts."""
        project = _create_project(session)
        _create_sample(session, project, "S1", {
            "Tissue": "Liver",
            "ASSAY_METHOD": "RNA-Seq",
        })
        session.commit()

        response = client.get(
            "/api/v1/samples/search",
            params={"projectid": project.project_id},
        )
        assert response.status_code == 200
        sample = response.json()["data"][0]
        assert isinstance(sample["attributes"], list)
        attr_keys = [a["key"] for a in sample["attributes"]]
        assert "Tissue" in attr_keys
        assert "ASSAY_METHOD" in attr_keys


# ──────────────────────────────────────────────────────────────────
# POST /api/v1/samples/search
# ──────────────────────────────────────────────────────────────────


class TestV1PostSearch:
    """Tests for POST /api/v1/samples/search"""

    def test_post_basic_filter(self, client: TestClient, session: Session):
        """POST with projectid filter returns matching samples."""
        project = _create_project(session)
        _create_sample(session, project, "S1")
        _create_sample(session, project, "S2")
        session.commit()

        response = client.post(
            "/api/v1/samples/search",
            json={"filter_on": {"projectid": project.project_id}},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["total_items"] == 2
        assert data["current_page"] == 1
        assert data["per_page"] == 20

    def test_post_tag_filter(self, client: TestClient, session: Session):
        """POST with tags filter matches attributes."""
        project = _create_project(session)
        _create_sample(session, project, "S1", {"USUBJID": "CA123-01"})
        _create_sample(session, project, "S2", {"USUBJID": "CA123-02"})
        session.commit()

        response = client.post(
            "/api/v1/samples/search",
            json={
                "filter_on": {
                    "tags": {"USUBJID": "CA123-01"},
                },
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["total_items"] == 1
        assert data["data"][0]["sample_id"] == "S1"

    def test_post_combined_filter(self, client: TestClient, session: Session):
        """POST with projectid + tags combined."""
        p1 = _create_project(session, "P1")
        p2 = _create_project(session, "P2")
        _create_sample(session, p1, "S1", {"USUBJID": "CA123-01"})
        _create_sample(session, p2, "S2", {"USUBJID": "CA123-01"})
        session.commit()

        response = client.post(
            "/api/v1/samples/search",
            json={
                "filter_on": {
                    "projectid": p1.project_id,
                    "tags": {"USUBJID": "CA123-01"},
                },
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["total_items"] == 1
        assert data["data"][0]["project_id"] == p1.project_id

    def test_post_list_values_or(self, client: TestClient, session: Session):
        """POST with list values for projectid matches any (OR)."""
        p1 = _create_project(session, "P1")
        p2 = _create_project(session, "P2")
        p3 = _create_project(session, "P3")
        _create_sample(session, p1, "S1")
        _create_sample(session, p2, "S2")
        _create_sample(session, p3, "S3")
        session.commit()

        response = client.post(
            "/api/v1/samples/search",
            json={
                "filter_on": {
                    "projectid": [p1.project_id, p2.project_id],
                },
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["total_items"] == 2

    def test_post_pagination(self, client: TestClient, session: Session):
        """POST respects page and per_page, total is full count."""
        project = _create_project(session)
        for i in range(5):
            _create_sample(session, project, f"S{i}")
        session.commit()

        # Page 1, per_page=2
        response = client.post(
            "/api/v1/samples/search",
            json={
                "filter_on": {"projectid": project.project_id},
                "page": 1,
                "per_page": 2,
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["total_items"] == 5
        assert data["current_page"] == 1
        assert data["per_page"] == 2
        assert len(data["data"]) == 2
        assert data["has_next"] is True

        # Page 3, per_page=2 — should get 1 result
        response = client.post(
            "/api/v1/samples/search",
            json={
                "filter_on": {"projectid": project.project_id},
                "page": 3,
                "per_page": 2,
            },
        )
        data = response.json()
        assert data["total_items"] == 5
        assert len(data["data"]) == 1
        assert data["has_next"] is False
        assert data["has_prev"] is True

    def test_post_case_insensitive_tag_keys(
        self, client: TestClient, session: Session
    ):
        """POST tag search is case-insensitive on keys."""
        project = _create_project(session)
        _create_sample(session, project, "S1", {"ASSAY_METHOD": "RNA-Seq"})
        session.commit()

        # lowercase key should match uppercase attribute
        response = client.post(
            "/api/v1/samples/search",
            json={
                "filter_on": {
                    "tags": {"assay_method": "RNA-Seq"},
                },
            },
        )
        assert response.status_code == 200
        assert response.json()["total_items"] == 1

    def test_post_empty_filter_returns_all(
        self, client: TestClient, session: Session
    ):
        """POST with empty filter_on returns all samples."""
        project = _create_project(session)
        _create_sample(session, project, "S1")
        _create_sample(session, project, "S2")
        session.commit()

        response = client.post(
            "/api/v1/samples/search",
            json={"filter_on": {}},
        )
        assert response.status_code == 200
        assert response.json()["total_items"] == 2

    def test_post_empty_body_uses_defaults(
        self, client: TestClient, session: Session
    ):
        """POST with minimal body uses defaults for page and per_page."""
        project = _create_project(session)
        _create_sample(session, project, "S1")
        session.commit()

        response = client.post(
            "/api/v1/samples/search",
            json={},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["current_page"] == 1
        assert data["per_page"] == 20
