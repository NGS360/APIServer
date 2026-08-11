""" Test cases for the authenticated presigned-download endpoint """
import pytest

from api.files.routes import DOWNLOAD_URL_TTL_SECONDS

URL = "/api/v1/files/download-url"
PATH = "s3://test-data-bucket/project/P-1/reads.fastq.gz"


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

    def test_a_caller_without_file_download_is_refused(self, restricted_client):
        r = restricted_client.get(URL, params={"path": PATH})
        assert r.status_code == 403
        assert "file:download" in r.json()["detail"]

    def test_the_default_role_is_enough(self, client):
        """
        `member` holds file:download, so every existing user can use this the
        moment it ships -- no grants needed for the frontend to migrate onto it.
        """
        from api.rbac.roles import DEFAULT_ROLE_NAME, ROLE_DEFINITIONS

        assert any(
            str(p) == "file:download"
            for p in ROLE_DEFINITIONS[DEFAULT_ROLE_NAME].permissions
        )
        assert client.get(URL, params={"path": PATH}).status_code == 200

    def test_an_anonymous_caller_is_refused(self, unauthenticated_client):
        assert unauthenticated_client.get(
            URL, params={"path": PATH}
        ).status_code == 401


class TestTheOldRouteStillWorks:
    """
    GET /files/download stays open and unguarded until the frontend has moved.

    Guarding it would 401 every download in the product: the UI uses it as a
    plain link, and a browser following a link cannot send a token. These pin
    that it is still reachable, so closing it has to be a deliberate change.
    """

    def test_it_is_still_anonymous(self, unauthenticated_client):
        r = unauthenticated_client.get(
            "/api/v1/files/download", params={"path": PATH},
            follow_redirects=False,
        )
        assert r.status_code == 307

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
