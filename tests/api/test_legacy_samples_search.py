"""
Tests for legacy /api/v0/samples/search compatibility endpoints.
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
# GET /api/v0/samples/search
# ──────────────────────────────────────────────────────────────────


class TestLegacyGetSearch:
    """Tests for GET /api/v0/samples/search"""

    def test_search_by_projectid(self, client: TestClient, session: Session):
        """Search by projectid returns matching samples."""
        project = _create_project(session)
        _create_sample(session, project, "S1", {"Tissue": "Liver"})
        _create_sample(session, project, "S2", {"Tissue": "Heart"})
        session.commit()

        response = client.get(
            "/api/v0/samples/search",
            params={"projectid": project.project_id},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 2
        assert len(data["hits"]) == 2
        # Verify response shape
        for hit in data["hits"]:
            assert "samplename" in hit
            assert "projectid" in hit
            assert hit["projectid"] == project.project_id

    def test_search_by_samplename(self, client: TestClient, session: Session):
        """Search by samplename returns the matching sample."""
        project = _create_project(session)
        _create_sample(session, project, "MySample", {"Tissue": "Liver"})
        _create_sample(session, project, "Other", {"Tissue": "Heart"})
        session.commit()

        response = client.get(
            "/api/v0/samples/search",
            params={"samplename": "MySample"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 1
        assert data["hits"][0]["samplename"] == "MySample"

    def test_combined_search(self, client: TestClient, session: Session):
        """Combined projectid + samplename returns intersection."""
        p1 = _create_project(session, "P1")
        p2 = _create_project(session, "P2")
        _create_sample(session, p1, "SharedName")
        _create_sample(session, p2, "SharedName")
        session.commit()

        response = client.get(
            "/api/v0/samples/search",
            params={"projectid": p1.project_id, "samplename": "SharedName"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 1
        assert data["hits"][0]["projectid"] == p1.project_id

    def test_search_by_attribute_as_query_param(self, client: TestClient, session: Session):
        """Unknown query params are searched as attributes (case-insensitive key)."""
        project = _create_project(session)
        _create_sample(session, project, "S1", {"ASSAY_METHOD": "RNA-Seq"})
        _create_sample(session, project, "S2", {"ASSAY_METHOD": "WES"})
        session.commit()

        # lowercase key should match uppercase attribute
        response = client.get(
            "/api/v0/samples/search",
            params={"assay_method": "RNA-Seq"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 1
        assert data["hits"][0]["samplename"] == "S1"

    def test_search_by_created_on(self, client: TestClient, session: Session):
        """Search by created_on matches date prefix of created_at."""
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
            "/api/v0/samples/search",
            params={"created_on": "2026-01-21"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 1
        assert data["hits"][0]["samplename"] == "S1"

    def test_empty_results(self, client: TestClient, session: Session):
        """Non-matching query returns empty results."""
        project = _create_project(session)
        _create_sample(session, project, "S1")
        session.commit()

        response = client.get(
            "/api/v0/samples/search",
            params={"projectid": "nonexistent"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 0
        assert data["hits"] == []

    def test_tags_are_flat_dict(self, client: TestClient, session: Session):
        """Verify tags in response are flat dict format."""
        project = _create_project(session)
        _create_sample(session, project, "S1", {
            "Tissue": "Liver",
            "ASSAY_METHOD": "RNA-Seq",
            "CREATED_BY": "testuser",
        })
        session.commit()

        response = client.get(
            "/api/v0/samples/search",
            params={"projectid": project.project_id},
        )
        assert response.status_code == 200
        hit = response.json()["hits"][0]
        assert isinstance(hit["tags"], dict)
        assert hit["tags"]["Tissue"] == "Liver"
        assert hit["tags"]["ASSAY_METHOD"] == "RNA-Seq"
        assert hit["tags"]["CREATED_BY"] == "testuser"

    def test_sample_without_attributes_has_null_tags(self, client: TestClient, session: Session):
        """Sample with no attributes returns tags as null."""
        project = _create_project(session)
        _create_sample(session, project, "BareSample")
        session.commit()

        response = client.get(
            "/api/v0/samples/search",
            params={"samplename": "BareSample"},
        )
        assert response.status_code == 200
        hit = response.json()["hits"][0]
        assert hit["tags"] is None

    def test_no_params_returns_all(self, client: TestClient, session: Session):
        """GET with no params returns all samples."""
        project = _create_project(session)
        _create_sample(session, project, "S1")
        _create_sample(session, project, "S2")
        session.commit()

        response = client.get("/api/v0/samples/search")
        assert response.status_code == 200
        assert response.json()["total"] == 2


# ──────────────────────────────────────────────────────────────────
# POST /api/v0/samples/search
# ──────────────────────────────────────────────────────────────────


class TestLegacyPostSearch:
    """Tests for POST /api/v0/samples/search"""

    def test_post_basic_filter(self, client: TestClient, session: Session):
        """POST with projectid filter returns matching samples."""
        project = _create_project(session)
        _create_sample(session, project, "S1")
        _create_sample(session, project, "S2")
        session.commit()

        response = client.post(
            "/api/v0/samples/search",
            json={"filter_on": {"projectid": project.project_id}},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 2
        assert data["page"] == 1
        assert data["per_page"] == 100

    def test_post_tag_filter(self, client: TestClient, session: Session):
        """POST with tags filter matches attributes."""
        project = _create_project(session)
        _create_sample(session, project, "S1", {"USUBJID": "CA123-01"})
        _create_sample(session, project, "S2", {"USUBJID": "CA123-02"})
        session.commit()

        response = client.post(
            "/api/v0/samples/search",
            json={
                "filter_on": {
                    "tags": {"USUBJID": "CA123-01"},
                },
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 1
        assert data["hits"][0]["samplename"] == "S1"

    def test_post_combined_filter(self, client: TestClient, session: Session):
        """POST with projectid + tags combined."""
        p1 = _create_project(session, "P1")
        p2 = _create_project(session, "P2")
        _create_sample(session, p1, "S1", {"USUBJID": "CA123-01"})
        _create_sample(session, p2, "S2", {"USUBJID": "CA123-01"})
        session.commit()

        response = client.post(
            "/api/v0/samples/search",
            json={
                "filter_on": {
                    "projectid": p1.project_id,
                    "tags": {"USUBJID": "CA123-01"},
                },
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 1
        assert data["hits"][0]["projectid"] == p1.project_id

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
            "/api/v0/samples/search",
            json={
                "filter_on": {
                    "projectid": [p1.project_id, p2.project_id],
                },
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 2

    def test_post_pagination(self, client: TestClient, session: Session):
        """POST respects page and per_page, total is full count."""
        project = _create_project(session)
        for i in range(5):
            _create_sample(session, project, f"S{i}")
        session.commit()

        # Page 1, per_page=2
        response = client.post(
            "/api/v0/samples/search",
            json={
                "filter_on": {"projectid": project.project_id},
                "page": 1,
                "per_page": 2,
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 5
        assert data["page"] == 1
        assert data["per_page"] == 2
        assert len(data["hits"]) == 2

        # Page 3, per_page=2 — should get 1 result
        response = client.post(
            "/api/v0/samples/search",
            json={
                "filter_on": {"projectid": project.project_id},
                "page": 3,
                "per_page": 2,
            },
        )
        data = response.json()
        assert data["total"] == 5
        assert len(data["hits"]) == 1

    def test_post_case_insensitive_tag_keys(self, client: TestClient, session: Session):
        """POST tag search is case-insensitive on keys."""
        project = _create_project(session)
        _create_sample(session, project, "S1", {"ASSAY_METHOD": "RNA-Seq"})
        session.commit()

        # lowercase key should match uppercase attribute
        response = client.post(
            "/api/v0/samples/search",
            json={
                "filter_on": {
                    "tags": {"assay_method": "RNA-Seq"},
                },
            },
        )
        assert response.status_code == 200
        assert response.json()["total"] == 1

    def test_post_empty_filter_returns_all(self, client: TestClient, session: Session):
        """POST with empty filter_on returns all samples."""
        project = _create_project(session)
        _create_sample(session, project, "S1")
        _create_sample(session, project, "S2")
        session.commit()

        response = client.post(
            "/api/v0/samples/search",
            json={"filter_on": {}},
        )
        assert response.status_code == 200
        assert response.json()["total"] == 2

    def test_post_empty_body_uses_defaults(self, client: TestClient, session: Session):
        """POST with minimal body uses defaults for page and per_page."""
        project = _create_project(session)
        _create_sample(session, project, "S1")
        session.commit()

        response = client.post(
            "/api/v0/samples/search",
            json={},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["page"] == 1
        assert data["per_page"] == 100
