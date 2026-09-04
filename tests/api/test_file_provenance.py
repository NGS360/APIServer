"""
Tests for the two provenance fields on a file record.

They answer different questions and must not be collapsed into one:

  created_by    who the file belongs to -- client-supplied, because the batch
                pipelines register files on behalf of the scientist who asked
                for the work. Validated so it cannot become free text.
  submitted_by  who made the API call -- derived from the authenticated
                caller, never accepted from a request.

The distinction is load-bearing. In production 39,459 file rows carry a
created_by, naming 42 people, of whom only 2 hold an API key: nearly everyone
named is someone a pipeline registered files *for*, not someone who called.
Overwriting created_by with the caller would have replaced all 42 with a single
service key's owner and destroyed the only attribution those rows have.
"""

import pytest

from api.files import services
from api.files.models import FileCreate
from fastapi import HTTPException
from tests.conftest import persist_user


BASE = "/api/v1/files"


@pytest.fixture(name="author")
def author_fixture(session):
    """A real account that is *not* the caller -- the on-behalf-of case."""
    return persist_user(session, "labscientist")


class TestCreatedByIsAnAcceptedClaim:
    """created_by keeps working as delegated attribution."""

    def test_a_caller_may_name_someone_else(self, client, session, test_project, author):
        """
        The whole point of the field: one credential registers files for a
        colleague who has none. This is the demux pipeline's shape.
        """
        response = client.post(BASE, json={
            "uri": "s3://bucket/project/P-19900109-0001/on_behalf.fastq.gz",
            "project_id": test_project.project_id,
            "created_by": author.username,
            "source": "NGS360_demux",
        })

        assert response.status_code == 201, response.text
        body = response.json()
        assert body["created_by"] == "labscientist"
        # The caller is recorded too, separately, without displacing the author.
        assert body["submitted_by"] == "testuser"

    def test_an_omitted_claim_stays_null(self, client, test_project):
        """
        594,894 production rows have no created_by. Attribution is optional and
        must not start being invented.
        """
        response = client.post(BASE, json={
            "uri": "s3://bucket/project/P-19900109-0001/no_author.txt",
            "project_id": test_project.project_id,
        })

        assert response.status_code == 201, response.text
        assert response.json()["created_by"] is None
        assert response.json()["submitted_by"] == "testuser"

    def test_a_blank_claim_is_treated_as_absent(self, client, test_project):
        """An empty form field should not become an empty-string author."""
        response = client.post(BASE, json={
            "uri": "s3://bucket/project/P-19900109-0001/blank_author.txt",
            "project_id": test_project.project_id,
            "created_by": "   ",
        })

        assert response.status_code == 201, response.text
        assert response.json()["created_by"] is None

    def test_a_claim_is_stored_in_the_accounts_own_spelling(self, session, test_project, author):
        """
        The column is joined against `users` to answer "whose files are these".
        Canonicalising on write keeps that join total.
        """
        record = services.create_file(
            session,
            FileCreate(
                uri="s3://bucket/project/P-19900109-0001/canonical.txt",
                project_id=test_project.project_id,
                created_by="  labscientist  ",
            ),
        )

        assert record.created_by == author.username


class TestCreatedByMustNameARealAccount:
    """
    The field was previously free text. Validation is what stops it decaying,
    and it costs nothing today: all 39,459 production claims resolve, exact
    case, no padding, spanning five months of traffic.
    """

    def test_an_unknown_author_is_rejected(self, client, test_project):
        response = client.post(BASE, json={
            "uri": "s3://bucket/project/P-19900109-0001/ghost.txt",
            "project_id": test_project.project_id,
            "created_by": "not-a-real-person",
        })

        assert response.status_code == 422
        assert "does not match a known NGS360 account" in response.text

    def test_the_file_is_not_created_when_the_author_is_rejected(
        self, client, session, test_project
    ):
        """A rejected claim must not leave a half-registered file behind."""
        uri = "s3://bucket/project/P-19900109-0001/rejected.txt"
        client.post(BASE, json={
            "uri": uri,
            "project_id": test_project.project_id,
            "created_by": "not-a-real-person",
        })

        from sqlmodel import select

        from api.files.models import File

        assert session.exec(select(File).where(File.uri == uri)).first() is None

    def test_the_service_layer_rejects_it_too(self, session, test_project):
        """
        Validation belongs below the route, so manifest ingestion and any other
        internal caller gets the same guarantee.
        """
        with pytest.raises(HTTPException) as excinfo:
            services.create_file(
                session,
                FileCreate(
                    uri="s3://bucket/project/P-19900109-0001/direct.txt",
                    project_id=test_project.project_id,
                    created_by="not-a-real-person",
                ),
            )

        assert excinfo.value.status_code == 422


class TestSubmittedByComesFromTheCaller:
    """The accountability half: server-derived, and not negotiable."""

    def test_a_client_cannot_set_it(self, client, test_project):
        """
        If the request could set it, it would be worth exactly as much as
        created_by was -- so FileCreate forbids the field outright.
        """
        response = client.post(BASE, json={
            "uri": "s3://bucket/project/P-19900109-0001/spoof.txt",
            "project_id": test_project.project_id,
            "submitted_by": "somebody-else",
        })

        assert response.status_code == 422
        assert "submitted_by" in response.text

    def test_a_spoofed_created_by_does_not_reach_submitted_by(
        self, client, test_project, author
    ):
        """
        Naming someone else as author is allowed; being recorded as them is not.
        """
        response = client.post(BASE, json={
            "uri": "s3://bucket/project/P-19900109-0001/both.txt",
            "project_id": test_project.project_id,
            "created_by": author.username,
        })

        assert response.status_code == 201, response.text
        assert response.json()["submitted_by"] == "testuser"
        assert response.json()["submitted_by"] != response.json()["created_by"]

    def test_an_anonymous_caller_leaves_it_null(self, unauthenticated_client, test_project):
        """
        POST /files still has no guard, so anonymous registration is possible.
        Recording an unknown submitter as null is honest; the alternative is
        putting a value nobody asserted into an accountability column.
        """
        response = unauthenticated_client.post(BASE, json={
            "uri": "s3://bucket/project/P-19900109-0001/anon.txt",
            "project_id": test_project.project_id,
        })

        assert response.status_code == 201, response.text
        assert response.json()["submitted_by"] is None

    def test_the_upload_route_records_it_as_well(self, client, test_project, author):
        """Both write paths, not just the JSON one."""
        response = client.post(
            f"{BASE}/upload",
            data={
                "filename": "uploaded.txt",
                "project_id": test_project.project_id,
                "created_by": author.username,
            },
            files={"content": ("uploaded.txt", b"contents", "text/plain")},
        )

        assert response.status_code == 201, response.text
        assert response.json()["created_by"] == "labscientist"
        assert response.json()["submitted_by"] == "testuser"

    def test_the_upload_route_validates_the_claim(
        self, client, test_project, mock_s3_client
    ):
        """
        And rejects before writing anything. The upload path has real side
        effects, so validating late would trade a bad row for an orphaned S3
        object -- which is harder to notice and harder to clean up.
        """
        response = client.post(
            f"{BASE}/upload",
            data={
                "filename": "bad_author.txt",
                "project_id": test_project.project_id,
                "created_by": "not-a-real-person",
            },
            files={"content": ("bad_author.txt", b"contents", "text/plain")},
        )

        assert response.status_code == 422
        assert "does not match a known NGS360 account" in response.text
        stored = [
            key
            for keys in mock_s3_client.uploaded_files.values()
            for key in keys
        ]
        assert stored == []


class TestProvenanceIsNotRewritable:
    """
    PATCH exists to fix a URI. Attribution is not a typo to be corrected in
    passing -- and production has issued zero PATCH /files requests in 30 days,
    so nothing depends on it being possible.
    """

    def test_created_by_cannot_be_patched(self, superuser_client, test_project, author):
        client = superuser_client
        created = client.post(BASE, json={
            "uri": "s3://bucket/project/P-19900109-0001/immutable.txt",
            "project_id": test_project.project_id,
            "created_by": author.username,
        })
        assert created.status_code == 201, created.text
        file_id = created.json()["id"]

        response = client.patch(f"{BASE}/{file_id}", json={"created_by": "testuser"})

        assert response.status_code == 422
        assert client.get(f"{BASE}/{file_id}").json()["created_by"] == "labscientist"

    def test_submitted_by_cannot_be_patched(self, superuser_client, test_project):
        client = superuser_client
        created = client.post(BASE, json={
            "uri": "s3://bucket/project/P-19900109-0001/immutable2.txt",
            "project_id": test_project.project_id,
        })
        assert created.status_code == 201, created.text
        file_id = created.json()["id"]

        response = client.patch(f"{BASE}/{file_id}", json={"submitted_by": "somebody"})

        assert response.status_code == 422
        assert client.get(f"{BASE}/{file_id}").json()["submitted_by"] == "admin"

    def test_a_uri_correction_still_works(self, superuser_client, test_project):
        """The documented use case must not be collateral damage."""
        client = superuser_client
        created = client.post(BASE, json={
            "uri": "s3://wrong-bucket/project/P-19900109-0001/typo.txt",
            "project_id": test_project.project_id,
        })
        assert created.status_code == 201, created.text

        response = client.patch(
            f"{BASE}/{created.json()['id']}",
            json={"uri": "s3://right-bucket/project/P-19900109-0001/typo.txt"},
        )

        assert response.status_code == 200, response.text
        assert response.json()["uri"].startswith("s3://right-bucket/")
