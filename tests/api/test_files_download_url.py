""" Test cases for the authenticated presigned-download endpoint """
import pytest

from api.files.routes import DOWNLOAD_URL_TTL_SECONDS

URL = "/api/v1/files/download-url"
# Under the configured upload store, which is a signable location as of
# 2026-10-08. An arbitrary bucket is no longer signable by anyone, so a
# test of the signing mechanics has to name somewhere the platform owns.
PATH = "s3://my-storage-bucket/project/P-1/reads.fastq.gz"

#: Well formed, and none of the platform's business. Signable by nobody.
FOREIGN = "s3://someone-elses-bucket/private/file.txt"


class TestPresignedURL:

    def test_returns_a_url_and_its_lifetime(self, client):
        r = client.get(URL, params={"path": PATH})
        assert r.status_code == 200
        body = r.json()
        assert body["url"]
        assert body["expires_in"] == DOWNLOAD_URL_TTL_SECONDS

    def test_the_reported_lifetime_matches_what_was_requested(self, client, monkeypatch):
        """
        expires_in is a promise about when the URL stops working. If the route
        let generate_presigned_url fall back to its own default, changing that
        default would make this response lie.
        """
        seen = {}

        from api.files import services

        original = services.generate_presigned_url

        def spy(s3_path, s3_client=None, expiration=3600):
            seen["expiration"] = expiration
            return original(s3_path, s3_client=s3_client, expiration=expiration)

        monkeypatch.setattr(services, "generate_presigned_url", spy)
        body = client.get(URL, params={"path": PATH}).json()
        assert seen["expiration"] == body["expires_in"]

    def test_the_response_is_not_cacheable(self, client):
        """A presigned URL is a bearer credential for the object; a shared proxy
        holding one would hand it to whoever asks next."""
        r = client.get(URL, params={"path": PATH})
        assert r.headers["cache-control"] == "no-store"

    def test_path_is_required(self, client):
        assert client.get(URL).status_code == 422


class TestAuthorization:

    def test_a_foreign_bucket_is_refused_whatever_the_caller_holds(
        self, restricted_client
    ):
        """
        Rewritten 2026-10-08. It previously asserted that this caller was
        refused *because it lacked file:download* -- a permission rule. There is
        no longer any URI that a permission opens: a URI is either one of the
        platform's locations, in which case the project's restriction decides,
        or it is not, in which case nobody may have it signed.
        """
        r = restricted_client.get(URL, params={"path": FOREIGN})
        assert r.status_code == 403

    def test_holding_file_download_does_not_help(self, client_with_permissions):
        """
        The half that changed, and the reason the rule moved off permissions.

        Granting `file:download` globally used to make every unresolved URI
        signable, which meant lab_manager, auditor, admin and every superuser
        could have any key in any bucket the API's IAM role can read signed for
        them. The protection was a privilege, so it was only ever as narrow as
        the narrowest role that held it.
        """
        from api.rbac.permissions import Permission

        api = client_with_permissions([Permission.FILE_DOWNLOAD], username="dl")
        assert api.get(URL, params={"path": FOREIGN}).status_code == 403

    def test_member_still_does_not_hold_file_download(self):
        """
        Kept from the previous version of this class, because it is still true
        and still load-bearing: while `member` held it, the project check was
        vacuous -- has_in_project short-circuits on a global grant.
        """
        from api.rbac.roles import DEFAULT_ROLE_NAME, ROLE_DEFINITIONS

        member = {str(p) for p in ROLE_DEFINITIONS[DEFAULT_ROLE_NAME].permissions}
        assert "file:download" not in member
        assert "file:read" in member, "reads stay global; only downloading moved"

    def test_an_anonymous_caller_is_refused(self, unauthenticated_client):
        assert unauthenticated_client.get(
            URL, params={"path": PATH}
        ).status_code == 401


class TestTheOldRouteStillWorks:
    """
    GET /files/download still serves the same redirect, but now requires auth.

    It was left open on the grounds that the UI used it as a plain link and a
    browser following a link cannot send a token. The frontend moved (it fetches
    /files/download-url with its token and navigates itself), so it was guarded
    on 2026-09-09. These pin the part that matters for compatibility: the
    response is still a 307 to the same place, so nothing that already
    authenticates had to change.
    """

    def test_it_now_requires_authentication(self, unauthenticated_client):
        r = unauthenticated_client.get(
            "/api/v1/files/download", params={"path": PATH},
            follow_redirects=False,
        )
        assert r.status_code == 401

    def test_it_redirects_to_the_same_place_the_new_route_returns(self, client):
        redirect = client.get(
            "/api/v1/files/download", params={"path": PATH},
            follow_redirects=False,
        )
        returned = client.get(URL, params={"path": PATH}).json()["url"]
        # Compare without the signature, which is time-dependent.
        assert redirect.headers["location"].split("?")[0] == returned.split("?")[0]


@pytest.mark.parametrize("bad", ["", "not-a-uri", "s3://bucket-only"])
def test_an_invalid_path_is_rejected_not_signed(client, bad):
    """Signing an unparseable path would hand back a URL that 404s at S3."""
    assert client.get(URL, params={"path": bad}).status_code in (400, 422)
