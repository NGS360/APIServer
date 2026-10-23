"""
Which S3 locations the platform will hand out credentials for.

Added 2026-10-08. The rule: `generate_presigned_url` may sign, and
`GET /files/list` may enumerate, only a URI in one of four places --

* a project, resolved by any `scope_for_uri` strategy;
* a registered sequencing run folder;
* a registered vendor inbound prefix;
* the platform's own upload store.

-- and nothing else, for **every** caller including superusers.

This replaced "an unresolved URI requires global `file:download`". That form was
a privilege rather than a boundary: `lab_manager`, `auditor`, `admin` and every
superuser held the permission, so for those principals the endpoint was an
arbitrary-S3-read proxy over whatever the API's own IAM role can reach. There is
no principal for whom signing a stranger's bucket is correct, which is why this
is a property of the location.

Authorisation is a separate question, answered afterwards: a signable URI inside
a *restricted* project still requires membership. See
tests/api/test_file_download_scope.py.

The vendor and upload-store locations were added on measurement rather than
taste. All 89 download requests into vendor buckets over 28 days named a project
id that exists -- none lacked one -- so vendor paths resolve to their project and
inherit its restriction. The upload store had to be a location in its own right
because uploads against a run, sample or QC record carry no project id at all,
and a may_sign check built only from the data and results buckets rejected every
upload. The test suite caught that; production would have caught it otherwise.
"""
from datetime import date

import pytest

from api.files.scope import is_wellformed, may_sign
from api.project.models import Project
from api.runs.models import SequencingRun
from api.vendors.models import Vendor

LIST = "/api/v1/files/list"


@pytest.fixture(name="storage_root")
def storage_root_fixture():
    from core.config import get_settings

    return get_settings().STORAGE_ROOT_PATH.rstrip("/")


def make_project(session, project_id: str) -> Project:
    project = Project(project_id=project_id, name=project_id, created_by="t")
    session.add(project)
    session.commit()
    session.refresh(project)
    return project


def make_vendor(session, bucket: str) -> Vendor:
    vendor = Vendor(vendor_id="V1", name="Vendor", description="d", bucket=bucket)
    session.add(vendor)
    session.commit()
    return vendor


def make_run(session, run_id: str, folder: str) -> SequencingRun:
    run = SequencingRun(run_id=run_id, run_date=date(2026, 2, 1), machine_id="M1",
                        run_number="1", flowcell_id="FC1", run_folder_uri=folder)
    session.add(run)
    session.commit()
    return run


class TestTheFourLocations:

    def test_an_unset_bucket_setting_does_not_match_everything(self, session):
        """
        The data and results buckets come from *database settings*, which are
        unset in tests. A path naming a real project in one of them is therefore
        not signable here -- and that is the property worth pinning: an unset
        setting must not normalise to an empty prefix, because an empty prefix
        matches every bucket the API can read and makes inference unbounded.

        Project resolution through a real association is covered in
        tests/api/test_file_download_scope.py, where it does not depend on a
        setting being present.
        """
        make_project(session, "P-20260401-0001")
        assert not may_sign(
            session, "s3://bmsrd-ngs-data/P-20260401-0001/reads.bam"
        )

    def test_a_vendor_inbound_path_resolves_to_its_project(self, session):
        make_project(session, "P-20260401-0002")
        make_vendor(session, "s3://vendor-drop/incoming")
        uri = "s3://vendor-drop/incoming/P-20260401-0002/manifest.csv"
        assert may_sign(session, uri)

    def test_a_vendor_path_naming_an_unknown_project_is_not(self, session):
        make_vendor(session, "s3://vendor-drop/incoming")
        uri = "s3://vendor-drop/incoming/P-19000101-9999/manifest.csv"
        assert not may_sign(session, uri)

    def test_a_path_outside_the_vendor_prefix_is_not(self, session):
        make_project(session, "P-20260401-0003")
        make_vendor(session, "s3://vendor-drop/incoming")
        assert not may_sign(
            session, "s3://vendor-drop/elsewhere/P-20260401-0003/x.csv"
        )

    def test_a_run_folder_and_its_contents_are_signable(self, session):
        folder = "s3://raw/illumina/260401_X_1_FC"
        make_run(session, "260401_X_1_FC", folder)
        assert may_sign(session, folder), "the folder itself, for listing"
        assert may_sign(session, folder + "/Stats/Stats.json")

    def test_the_upload_store_is_signable(self, session, storage_root):
        assert may_sign(session, storage_root + "/run/some-uuid/report.html")

    def test_a_stranger_s_bucket_is_not(self, session):
        assert not may_sign(session, "s3://someone-elses-bucket/private/x.bam")


class TestListingIsConfinedTheSameWay:
    """
    Enumerating a bucket and signing a key in it are the same problem, and this
    route had neither constraint -- it would list any prefix the API's IAM role
    could read, with no authentication either. The authentication half is
    consumer work tracked separately; this is the location half.
    """

    def test_a_project_folder_can_be_listed(self, session, client, storage_root):
        r = client.get(LIST, params={"uri": storage_root + "/project/P-1/"})
        assert r.status_code != 403

    def test_a_foreign_prefix_cannot(self, session, client):
        r = client.get(LIST, params={"uri": "s3://someone-elses-bucket/data/"})
        assert r.status_code == 403

    def test_a_bare_bucket_cannot_either(self, session, client):
        """
        The hole this closes, and it is subtle enough to be worth its own test:
        a bucket root has no key, so a signing-shaped "is this well formed"
        check calls it malformed and lets it through. Dropping the key would
        then have been enough to enumerate any bucket the API can read.

        `is_wellformed(..., require_key=False)` is what makes listing check it.
        """
        assert not is_wellformed("s3://someone-elses-bucket/")
        assert is_wellformed("s3://someone-elses-bucket/", require_key=False)
        r = client.get(LIST, params={"uri": "s3://someone-elses-bucket/"})
        assert r.status_code == 403

    def test_a_malformed_uri_is_a_400_not_a_403(self, session, client):
        """
        A typo is a malformed request, not a refusal. Answering 403 would tell a
        caller they lack access to something that is not a location, and would
        make the two cases indistinguishable while they fix the request.
        """
        r = client.get(LIST, params={"uri": "not-a-uri"})
        assert r.status_code != 403


class TestNoPrincipalOverridesIt:

    def test_holding_file_download_globally_does_not(self, client_with_permissions):
        from api.rbac.permissions import Permission

        api = client_with_permissions([Permission.FILE_DOWNLOAD], username="dl2")
        r = api.get("/api/v1/files/download-url",
                    params={"path": "s3://someone-elses-bucket/x.bam"})
        assert r.status_code == 403

    def test_superuser_does_not(self, superuser_client):
        """
        The second place superuser does not short-circuit, after the
        restricted-project membership gate. An allowlist an administrator can
        step outside is not an allowlist.
        """
        r = superuser_client.get("/api/v1/files/download-url",
                                 params={"path": "s3://someone-elses-bucket/x.bam"})
        assert r.status_code == 403


class TestTheLocationRuleIgnoresTheEnforcementMode:
    """
    The regression that shipped in #459 and was caught by probing production.

    The refusal was folded into the guard's `granted` flag and handed to
    `decide()`, which applies RBAC_MODE. Production runs `dry_run`, so an
    unsignable URI was recorded `would_deny` and served a **200** -- the
    protection was inert in the only tier that mattered, while every test passed
    because the suite runs in `enforce`.

    Whether a URI is one of the platform's locations is a property of the URI.
    It is not an authorisation question, so no enforcement mode may soften it.
    That is what these tests pin, and they are written in the mode that hid the
    bug.

    Authorisation -- a restricted project's membership check -- stays
    mode-aware, because that one genuinely is a permission decision and is still
    being rolled out. See tests/api/test_file_download_scope.py.
    """

    @pytest.fixture
    def mode(self, monkeypatch):
        from core.config import get_settings

        def _set(value: str):
            monkeypatch.setenv("RBAC_MODE", value)
            monkeypatch.setenv("ENVIRONMENT", "dev")
            get_settings.cache_clear()
        yield _set
        get_settings.cache_clear()

    @pytest.mark.parametrize("mode_value", ["dry_run", "off", "enforce"])
    def test_a_foreign_bucket_is_refused_in_every_mode(
        self, client, mode, mode_value
    ):
        mode(mode_value)
        r = client.get("/api/v1/files/download-url",
                       params={"path": "s3://someone-elses-bucket/x.bam"})
        assert r.status_code == 403, mode_value

    @pytest.mark.parametrize("mode_value", ["dry_run", "off", "enforce"])
    def test_listing_a_foreign_bucket_is_refused_in_every_mode(
        self, client, mode, mode_value
    ):
        mode(mode_value)
        r = client.get(LIST, params={"uri": "s3://someone-elses-bucket/"})
        assert r.status_code == 403, mode_value

    def test_a_platform_location_is_still_served_in_dry_run(
        self, client, mode, storage_root
    ):
        """The other half: the rule refuses foreign URIs, not everything."""
        mode("dry_run")
        r = client.get("/api/v1/files/download-url",
                       params={"path": storage_root + "/run/u/report.html"})
        assert r.status_code == 200
