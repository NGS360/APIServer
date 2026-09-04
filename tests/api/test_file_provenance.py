"""
A file's recorded author comes from the authenticated caller, never the request.

Both create endpoints used to take `created_by` from the client -- a JSON field
on one, a form field on the other -- so provenance was whatever the caller
asserted. Meanwhile the ownership backfill and the project-creator fix both derive
authorship from the authenticated user, so the two halves of the system disagreed
about whether the caller could be trusted.

Two facts shaped the fix, both measured first rather than assumed:

* **Every row registered through these endpoints had a null `created_by`.** No
  caller was passing anything, so deriving it loses no attribution.
* **`FileCreate` sets `extra="forbid"`, and one caller registers ~1,500 files a
  week here.** Deleting the field would turn a request that sends the key into a
  422, and the database cannot distinguish "key absent" from "key present and
  null" -- so the field is accepted and discarded rather than rejected, with a log
  line so it can be deleted later on evidence.
"""
from sqlmodel import select

from api.files.models import File


def _stored(session, uri):
    return session.exec(select(File).where(File.uri == uri)).one()


class TestTheAuthorComesFromTheCaller:

    def test_create_records_the_authenticated_caller(self, client, session, test_project):
        uri = "s3://test-data-bucket/provenance/a.txt"
        r = client.post("/api/v1/files", json={
            "uri": uri, "project_id": test_project.project_id,
        })
        assert r.status_code == 201
        assert _stored(session, uri).created_by == "testuser"

    def test_a_claimed_author_is_discarded_not_stored(
        self, client, session, test_project
    ):
        """The spoofing case. The caller says someone else; the record says the
        caller."""
        uri = "s3://test-data-bucket/provenance/b.txt"
        r = client.post("/api/v1/files", json={
            "uri": uri, "project_id": test_project.project_id,
            "created_by": "somebody-else",
        })
        assert r.status_code == 201
        assert _stored(session, uri).created_by == "testuser"

    def test_a_claimed_author_does_not_cause_a_422(
        self, client, test_project
    ):
        """
        The compatibility requirement. FileCreate forbids extra fields, so
        removing `created_by` outright would break any caller still sending it --
        and one caller registers ~1,500 files a week through this endpoint.
        """
        r = client.post("/api/v1/files", json={
            "uri": "s3://test-data-bucket/provenance/c.txt",
            "project_id": test_project.project_id,
            "created_by": "somebody-else",
        })
        assert r.status_code == 201, r.text

    def test_an_explicit_null_is_also_accepted(self, client, test_project):
        """The case the database could not distinguish from the key being absent,
        and therefore the one that made rejection too risky."""
        r = client.post("/api/v1/files", json={
            "uri": "s3://test-data-bucket/provenance/d.txt",
            "project_id": test_project.project_id,
            "created_by": None,
        })
        assert r.status_code == 201, r.text

    def test_discarding_is_logged_so_the_field_can_be_removed_later(
        self, client, test_project, caplog
    ):
        """
        The log line is what turns "delete this field eventually" from a guess
        into a decision. Without it there is no way to tell whether any caller
        still sends the field.
        """
        client.post("/api/v1/files", json={
            "uri": "s3://test-data-bucket/provenance/e.txt",
            "project_id": test_project.project_id,
            "created_by": "somebody-else",
        })
        assert "discarding client-supplied created_by" in caplog.text
        assert "somebody-else" in caplog.text

    def test_no_log_line_when_the_field_is_absent(
        self, client, test_project, caplog
    ):
        """Otherwise the signal is useless -- every request would log."""
        client.post("/api/v1/files", json={
            "uri": "s3://test-data-bucket/provenance/f.txt",
            "project_id": test_project.project_id,
        })
        assert "discarding client-supplied" not in caplog.text


class TestTheUpdateEndpointCannotRewriteHistory:

    def test_created_by_is_not_an_updatable_field(self):
        """
        Rewriting who authored an existing file is editing history, not fixing
        data. The documented use case for PATCH is correcting a URI.
        """
        from api.files.models import FileUpdate

        assert "created_by" not in FileUpdate.model_fields

    def test_sending_it_is_refused_rather_than_ignored(
        self, superuser_client, session, test_project
    ):
        """
        Unlike the create endpoints, this one is already authenticated and
        superuser-gated, so there is no compatibility argument for tolerating it
        -- a 422 is the honest answer.
        """
        from api.files.models import File

        f = File(uri="s3://test-data-bucket/provenance/g.txt", storage_backend="S3",
                 created_by="original")
        session.add(f)
        session.commit()
        session.refresh(f)

        r = superuser_client.patch(f"/api/v1/files/{f.id}",
                                   json={"created_by": "rewritten"})
        assert r.status_code == 422
        session.expire_all()
        assert _stored(session, f.uri).created_by == "original"


class TestTheSchemaTellsTheTruth:

    def test_the_upload_form_no_longer_takes_created_by(self):
        from main import app

        op = app.openapi()["paths"]["/api/v1/files/upload"]["post"]
        body = op["requestBody"]["content"]
        schema_ref = list(body.values())[0]["schema"]
        name = schema_ref.get("$ref", "").rsplit("/", 1)[-1]
        props = app.openapi()["components"]["schemas"][name]["properties"]
        assert "created_by" not in props

    def test_create_still_advertises_it_but_says_it_is_ignored(self):
        """
        It has to stay in the schema while it is still accepted, or the generated
        clients and the API would disagree. The description is what stops it
        looking like a working field.
        """
        from api.files.models import FileCreate

        desc = FileCreate.model_fields["created_by"].description or ""
        assert "ignored" in desc.lower()
