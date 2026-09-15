"""
Downloads: may this caller download *this* file?

Open unless the project says otherwise. Downloads are permitted for any
authenticated caller; a project opts out by setting `download_restricted`, and
only then is `file:download` consulted.

This inverts what these tests originally asserted. The earlier policy required
project membership for every download, and seven tests here encoded that -- they
were rewritten rather than preserved, because they asserted the requirement that
was withdrawn. The measurement that changed it: one genomics workload read 66
projects 33,000,000 times in a month holding `member` and no memberships, so
default-deny meant either refusing it or maintaining 66 grants that made project
membership mean "reads everything".

What is under test now:

* **Unrestricted is open.** A non-member downloads freely. No permission is
  consulted at all on this path.
* **Restricted requires `file:download` on that project**, which project_viewer
  and above carry -- so a restricted project's members are its allowlist.
* **The resolver is unchanged**, and its ordering is still the policy. It now
  answers "whose restriction applies" instead of "whose membership is required",
  so the ordering tests express themselves through a restriction rather than
  through a refusal.
* **An unresolved URI still needs *global* `file:download`.** Unchanged, and
  load-bearing beyond authorization: generate_presigned_url signs any bucket and
  key it is given, so this is what stops the endpoint being an arbitrary-S3-read
  proxy.
* **Authentication is still required.** "Open" means open to platform users.

RBAC_MODE is `enforce` in tests, so refusals are 403s.
"""
from datetime import date

import pytest

from api.files.models import File, FileProject, FileSample, FileSequencingRun
from api.project.models import Project
from api.rbac.models import GrantSource, ProjectMember, Role
from api.rbac.permissions import Permission
from api.runs.models import SampleSequencingRun, SequencingRun
from api.samples.models import Sample

URL = "/api/v1/files/download-url"


def make_project(session, suffix: str) -> Project:
    project = Project(project_id=f"P-20260201-{suffix}", name=f"Project {suffix}",
                      created_by="t")
    session.add(project)
    session.commit()
    session.refresh(project)
    return project


def make_file(session, uri: str) -> File:
    f = File(uri=uri, storage_backend="S3")
    session.add(f)
    session.commit()
    session.refresh(f)
    return f


def make_run(session, run_id: str) -> SequencingRun:
    run = SequencingRun(run_id=run_id, run_date=date(2026, 2, 1),
                        machine_id="M1", run_number="1", flowcell_id="FC1")
    session.add(run)
    session.commit()
    session.refresh(run)
    return run


def put_sample_on_run(session, project: Project, run: SequencingRun, name: str):
    sample = Sample(sample_id=name, project_id=project.project_id)
    session.add(sample)
    session.commit()
    session.refresh(sample)
    session.add(SampleSequencingRun(sample_id=sample.id, sequencing_run_id=run.id,
                                    created_by="t"))
    session.commit()
    return sample


def restrict(session, project: Project):
    """Opt a project out of open downloads."""
    project.download_restricted = True
    session.add(project)
    session.commit()
    session.refresh(project)
    return project


def enrol(session, project: Project, username: str, role_name="project_viewer"):
    from sqlmodel import select

    from api.auth.models import User

    user = session.exec(select(User).where(User.username == username)).one()
    role = session.exec(select(Role).where(Role.name == role_name)).one()
    session.add(ProjectMember(project_id=project.id, user_id=user.id,
                              role_id=role.id, source=GrantSource.MANUAL))
    session.commit()


@pytest.fixture(name="scoped_client")
def scoped_client_fixture(client_with_permissions):
    """
    An authenticated caller holding the four global reads `member` keeps, and
    explicitly **not** file:download. Any download it manages has to have come
    from a project role.
    """
    return client_with_permissions(
        [Permission.PROJECT_READ, Permission.SAMPLE_READ,
         Permission.QCRECORD_READ, Permission.FILE_READ],
        username="scoped",
    )


class TestProjectAssociatedFilesAreStrict:

    def test_a_member_of_the_file_s_project_can_download_it(
        self, session, scoped_client
    ):
        project = make_project(session, "0001")
        f = make_file(session, "s3://bucket/p1/reads.fastq.gz")
        session.add(FileProject(file_id=f.id, project_id=project.id))
        session.commit()
        enrol(session, project, "scoped")

        assert scoped_client.get(URL, params={"path": f.uri}).status_code == 200

    def test_a_non_member_can_when_the_project_is_not_restricted(
        self, session, scoped_client
    ):
        """
        The policy, stated minimally. This caller holds no file:download at all,
        globally or on the project, and still gets in -- because nothing said it
        should not.
        """
        project = make_project(session, "0002")
        f = make_file(session, "s3://bucket/p2/reads.fastq.gz")
        session.add(FileProject(file_id=f.id, project_id=project.id))
        session.commit()

        assert scoped_client.get(URL, params={"path": f.uri}).status_code == 200

    def test_a_non_member_cannot_once_the_project_is_restricted(
        self, session, scoped_client
    ):
        """And the opt-out actually opts out."""
        project = make_project(session, "0022")
        f = make_file(session, "s3://bucket/p22/reads.fastq.gz")
        session.add(FileProject(file_id=f.id, project_id=project.id))
        session.commit()
        restrict(session, project)

        r = scoped_client.get(URL, params={"path": f.uri})
        assert r.status_code == 403
        assert "file:download" in r.json()["detail"]

    def test_a_member_can_download_from_a_restricted_project(
        self, session, scoped_client
    ):
        """Membership is the allowlist for a restricted project."""
        project = make_project(session, "0023")
        f = make_file(session, "s3://bucket/p23/reads.fastq.gz")
        session.add(FileProject(file_id=f.id, project_id=project.id))
        session.commit()
        restrict(session, project)
        enrol(session, project, "scoped")

        assert scoped_client.get(URL, params={"path": f.uri}).status_code == 200

    def test_membership_of_a_different_project_does_not_open_a_restricted_one(
        self, session, scoped_client
    ):
        """
        The isolation case, still needed. A check asking "does this user hold
        file:download anywhere" would pass the member test above and this one too.
        """
        mine = make_project(session, "0003")
        theirs = make_project(session, "0004")
        f = make_file(session, "s3://bucket/p4/reads.fastq.gz")
        session.add(FileProject(file_id=f.id, project_id=theirs.id))
        session.commit()
        restrict(session, theirs)
        enrol(session, mine, "scoped")

        assert scoped_client.get(URL, params={"path": f.uri}).status_code == 403

    def test_a_file_in_two_projects_is_reachable_from_either(
        self, session, scoped_client
    ):
        """A file genuinely belonging to two projects belongs to both."""
        a = make_project(session, "0005")
        b = make_project(session, "0006")
        f = make_file(session, "s3://bucket/shared/reads.fastq.gz")
        session.add(FileProject(file_id=f.id, project_id=a.id))
        session.add(FileProject(file_id=f.id, project_id=b.id))
        session.commit()
        enrol(session, b, "scoped")

        assert scoped_client.get(URL, params={"path": f.uri}).status_code == 200

    def test_a_sample_association_resolves_to_that_sample_s_project(
        self, session, scoped_client
    ):
        """filesample points at a sample, and a sample belongs to one project."""
        project = make_project(session, "0007")
        sample = Sample(sample_id="S-1", project_id=project.project_id)
        session.add(sample)
        session.commit()
        session.refresh(sample)
        f = make_file(session, "s3://bucket/p7/S-1.bam")
        session.add(FileSample(file_id=f.id, sample_id=sample.id))
        session.commit()
        enrol(session, project, "scoped")

        assert scoped_client.get(URL, params={"path": f.uri}).status_code == 200


class TestRunAssociatedFilesArePermissive:

    def test_a_member_of_any_project_on_the_run_can_download(
        self, session, scoped_client
    ):
        """
        The decided policy. A flowcell spans projects; demux output belongs to the
        run rather than to one of them.
        """
        a = make_project(session, "0010")
        b = make_project(session, "0011")
        run = make_run(session, "260201_M1_1_FC1")
        put_sample_on_run(session, a, run, "S-A")
        put_sample_on_run(session, b, run, "S-B")

        f = make_file(session, "s3://bucket/runs/FC1/demux_stats.csv")
        session.add(FileSequencingRun(file_id=f.id, sequencing_run_id=run.id))
        session.commit()

        enrol(session, b, "scoped")  # member of only one of the two
        assert scoped_client.get(URL, params={"path": f.uri}).status_code == 200

    def test_a_restricted_project_on_the_run_restricts_the_run_file(
        self, session, scoped_client
    ):
        """
        Permissive widens *which* projects are consulted; it does not skip the
        restriction. A run file whose run touches a restricted project needs
        permission on that project.
        """
        on_run = make_project(session, "0012")
        elsewhere = make_project(session, "0013")
        run = make_run(session, "260201_M1_2_FC2")
        put_sample_on_run(session, on_run, run, "S-C")

        f = make_file(session, "s3://bucket/runs/FC2/demux_stats.csv")
        session.add(FileSequencingRun(file_id=f.id, sequencing_run_id=run.id))
        session.commit()
        restrict(session, on_run)

        enrol(session, elsewhere, "scoped")
        assert scoped_client.get(URL, params={"path": f.uri}).status_code == 403

    def test_a_project_association_wins_over_the_run(self, session, scoped_client):
        """
        The ordering test, and the reason the resolver checks direct associations
        first. This file is on a run that also touches another project; if the run
        path were allowed to widen it, a member of that other project would get in
        and the strict case would silently have become the permissive one.
        """
        owner = make_project(session, "0014")
        also_on_run = make_project(session, "0015")
        run = make_run(session, "260201_M1_3_FC3")
        put_sample_on_run(session, owner, run, "S-D")
        put_sample_on_run(session, also_on_run, run, "S-E")

        f = make_file(session, "s3://bucket/p14/aligned.bam")
        session.add(FileProject(file_id=f.id, project_id=owner.id))
        session.add(FileSequencingRun(file_id=f.id, sequencing_run_id=run.id))
        session.commit()

        # Only the file's own project is restricted. The run's other project is
        # open, so if the run path were allowed to widen this, the restriction
        # would be bypassed and this caller would get in.
        restrict(session, owner)
        enrol(session, also_on_run, "scoped")
        assert scoped_client.get(URL, params={"path": f.uri}).status_code == 403


class TestUnresolvableURIs:

    def test_an_ordinary_user_cannot_download_an_unregistered_uri(
        self, session, scoped_client
    ):
        """
        "This file belongs to no project" is not evidence of permission. Without
        this, project scoping is bypassable by pointing at any path directly.
        """
        r = scoped_client.get(URL, params={"path": "s3://bucket/loose/file.txt"})
        assert r.status_code == 403

    def test_a_registered_file_with_no_association_is_also_refused(
        self, session, scoped_client
    ):
        make_file(session, "s3://bucket/orphan/file.txt")
        r = scoped_client.get(URL, params={"path": "s3://bucket/orphan/file.txt"})
        assert r.status_code == 403

    def test_a_global_holder_can_still_reach_raw_storage(
        self, client_with_permissions
    ):
        """
        The counterpart. lab_manager, auditor and admin hold global file:download
        for cross-project operation, and has_in_project honours a global grant, so
        project scoping does not restrict them. That is deliberate: a sequencing
        core operator enrolled in no projects still has to be able to work.
        """
        api = client_with_permissions([Permission.FILE_DOWNLOAD], username="global")
        assert api.get(
            URL, params={"path": "s3://bucket/loose/file.txt"}
        ).status_code == 200

    def test_a_superuser_is_unaffected(self, superuser_client):
        assert superuser_client.get(
            URL, params={"path": "s3://bucket/loose/file.txt"}
        ).status_code == 200


class TestTheOldRouteIsNoLongerTheBypass:
    """
    Inverted 2026-09-09, which the previous version of this class asked for.

    `GET /files/download` was unguarded, on the stated grounds that the UI used
    it as a plain link and a browser following a link cannot send an
    Authorization header. That stopped being true: the frontend fetches
    /files/download-url with its token and navigates itself, and the built bundle
    contains no reference to the old route. Browser traffic over the 30 days to
    09-09 was 41 requests -- 39 of them one bulk download on 08-15, then 2 on
    09-04 and none since.

    So it now carries the same guard. Its response is unchanged (307 to S3), so
    the ~1.1M requests a day that arrive on it already authenticated are
    unaffected; what changes is that anonymous callers and restricted projects
    are refused here too.
    """

    def test_the_two_routes_now_agree_on_a_restriction(
        self, session, scoped_client
    ):
        """The property the old class asserted the *absence* of."""
        project = make_project(session, "0020")
        f = make_file(session, "s3://bucket/p20/reads.fastq.gz")
        session.add(FileProject(file_id=f.id, project_id=project.id))
        session.commit()
        restrict(session, project)

        assert scoped_client.get(URL, params={"path": f.uri}).status_code == 403
        assert scoped_client.get(
            "/api/v1/files/download", params={"path": f.uri},
            follow_redirects=False,
        ).status_code == 403

    def test_the_old_route_now_requires_authentication(
        self, session, unauthenticated_client
    ):
        project = make_project(session, "0021")
        f = make_file(session, "s3://bucket/p21/reads.fastq.gz")
        session.add(FileProject(file_id=f.id, project_id=project.id))
        session.commit()

        assert unauthenticated_client.get(
            "/api/v1/files/download", params={"path": f.uri},
            follow_redirects=False,
        ).status_code == 401

    def test_an_authenticated_caller_still_gets_the_same_307(
        self, session, scoped_client
    ):
        """
        The compatibility guarantee, and the reason this needed no client
        changes: the response shape is untouched for anyone already sending
        credentials. htslib arrives with an API key, the project is unrestricted,
        so it gets exactly the redirect it got before.
        """
        project = make_project(session, "0024")
        f = make_file(session, "s3://bucket/p24/reads.fastq.gz")
        session.add(FileProject(file_id=f.id, project_id=project.id))
        session.commit()

        r = scoped_client.get(
            "/api/v1/files/download", params={"path": f.uri},
            follow_redirects=False,
        )
        assert r.status_code == 307
        assert r.headers["location"]


def test_the_resolver_is_not_confused_by_file_versioning(session):
    """
    A uri is re-registered on every upload to give versioning, so several File rows
    can share one uri. Associations on any version govern the bytes at that path,
    so all versions count -- taking only the newest would refuse a caller whose
    access came through an earlier registration.
    """
    from api.files.scope import scope_for_uri

    project = make_project(session, "0030")
    uri = "s3://bucket/p30/versioned.txt"
    old, new = make_file(session, uri), make_file(session, uri)
    session.add(FileProject(file_id=old.id, project_id=project.id))
    session.commit()

    scope = scope_for_uri(session, uri)
    assert scope.project_ids == frozenset({project.id})
    assert scope.origin == "project"
    assert new.id != old.id and new.uri == old.uri


class TestTheDecisionRecordsTheURI:
    """
    The URI has to reach the access log, or a refusal is not diagnosable.

    In the first clean production window, 88% of would_deny on file:download read
    "unregistered, 0 projects" -- and there was no way to tell whether those files
    are genuinely unregistered or whether the resolver's exact match on File.uri
    is missing a URI form that differs by prefix or encoding. The middleware logs
    request.url.path without the query string, so the input that produced the
    decision was invisible. That is the difference between "register these files"
    and "fix this code".
    """

    def _decisions(self, client, path):
        """Capture the decision records a request produced."""
        captured = {}
        from api.rbac import deps as rbac_deps

        original = rbac_deps.decide

        def spy(request, granted, permissions, scope, subject=None):
            # try/finally, because under enforce a refusal raises out of decide()
            # -- capturing after the call would miss exactly the records this
            # test cares about.
            try:
                original(request, granted, permissions, scope, subject)
            finally:
                captured.setdefault("records", []).extend(
                    getattr(request.state, "rbac_decisions", [])
                )

        import api.files.routes as file_routes
        file_routes.decide = spy
        try:
            client.get(URL, params={"path": path})
        finally:
            file_routes.decide = original
        return captured.get("records", [])

    def test_the_requested_uri_is_on_the_record(self, session, scoped_client):
        project = make_project(session, "0040")
        f = make_file(session, "s3://bucket/p40/reads.fastq.gz")
        session.add(FileProject(file_id=f.id, project_id=project.id))
        session.commit()
        enrol(session, project, "scoped")

        records = self._decisions(scoped_client, f.uri)
        assert records, "no decision was recorded at all"
        assert records[-1]["rbac_subject"] == f.uri

    def test_it_is_recorded_on_a_refusal_too(self, scoped_client):
        """The refusal is the case that needs it; an allow rarely gets read."""
        uri = "s3://bucket/nowhere/orphan.txt"
        records = self._decisions(scoped_client, uri)
        assert records[-1]["rbac_decision"] in ("deny", "would_deny")
        assert records[-1]["rbac_subject"] == uri

    def test_a_check_with_no_subject_omits_the_field(self, session):
        """
        Absent rather than null, so `ispresent(rbac_subject)` in Insights selects
        exactly the checks that have one.
        """
        from unittest.mock import MagicMock

        from api.rbac.deps import decide
        from api.rbac.permissions import Permission

        request = MagicMock()
        request.state = type("S", (), {})()
        decide(request, True, (Permission.PROJECT_READ,), scope=None)
        assert "rbac_subject" not in request.state.rbac_decisions[0]


class TestPathInferenceForUnregisteredFiles:
    """
    An unregistered file under a project id, in a bucket we own, belongs to that
    project.

    Added after production measurement: 63 of 75 unresolvable download attempts
    were pipeline *output* -- zUMIs count matrices, multiqc reports, WES variant
    calls -- written to <results-bucket>/<project-id>/... and never registered as
    File rows. Those are the scientific product; refusing them refuses the most
    legitimate traffic on the endpoint.

    The tests that matter here are the negative ones. Inferring a project from a
    path means the access decision rests on a naming convention, so the boundaries
    of that convention are the security property, and each one below is a way the
    fallback could have become a hole.
    """

    def test_a_member_can_download_unregistered_output_in_their_project(
        self, session, scoped_client
    ):
        project = make_project(session, "0050")
        enrol(session, project, "scoped")
        uri = (f"s3://test-results-bucket/{project.project_id}"
               "/scRNA-Seq/zUMIs/combined.dgecounts.rds")
        assert scoped_client.get(URL, params={"path": uri}).status_code == 200

    def test_a_non_member_can_when_the_inferred_project_is_open(
        self, session, scoped_client
    ):
        """
        This is the traffic the policy change exists to serve: unregistered
        pipeline output under a project prefix, read by someone who is not a
        member of it.
        """
        project = make_project(session, "0051")
        uri = (f"s3://test-results-bucket/{project.project_id}"
               "/scRNA-Seq/zUMIs/combined.dgecounts.rds")
        assert scoped_client.get(URL, params={"path": uri}).status_code == 200

    def test_a_non_member_cannot_when_the_inferred_project_is_restricted(
        self, session, scoped_client
    ):
        """Restriction reaches inferred files too, or it would be trivially evaded
        by never registering the output."""
        project = make_project(session, "0057")
        restrict(session, project)
        uri = (f"s3://test-results-bucket/{project.project_id}"
               "/scRNA-Seq/zUMIs/combined.dgecounts.rds")
        assert scoped_client.get(URL, params={"path": uri}).status_code == 403

    def test_the_data_bucket_counts_too(self, session, scoped_client):
        project = make_project(session, "0052")
        enrol(session, project, "scoped")
        uri = f"s3://test-data-bucket/{project.project_id}/manifest.csv"
        assert scoped_client.get(URL, params={"path": uri}).status_code == 200

    def test_a_bucket_we_do_not_own_is_not_inferred(self, session, scoped_client):
        """
        The security boundary. The guard mints a presigned URL against the API's
        own credentials, so inferring a project from an arbitrary bucket would let
        a member of that project reach any object whose key contains its id --
        anywhere the API's role can read.
        """
        project = make_project(session, "0053")
        enrol(session, project, "scoped")
        uri = f"s3://some-other-bucket/{project.project_id}/secret.txt"
        assert scoped_client.get(URL, params={"path": uri}).status_code == 403

    def test_a_project_id_that_does_not_exist_is_not_invented(
        self, session, scoped_client
    ):
        uri = "s3://test-results-bucket/P-19000101-0001/anything.rds"
        assert scoped_client.get(URL, params={"path": uri}).status_code == 403

    def test_a_project_id_inside_a_filename_does_not_count(
        self, session, scoped_client
    ):
        """
        Only a whole path segment is a project id. Otherwise anyone able to name a
        file could claim a project by embedding its id in the filename.
        """
        project = make_project(session, "0054")
        enrol(session, project, "scoped")
        uri = (f"s3://test-results-bucket/somewhere-else"
               f"/summary-{project.project_id}-final.csv")
        assert scoped_client.get(URL, params={"path": uri}).status_code == 403

    def test_a_path_with_no_project_id_is_still_refused(
        self, session, scoped_client
    ):
        """The run-level case: raw data laid out by instrument and run, not by
        project. Those resolve through the run association or not at all."""
        uri = ("s3://test-data-bucket/illumina/260828_A00267_0511_AHGG7FDRX7"
               "/Reports/html/index.html")
        assert scoped_client.get(URL, params={"path": uri}).status_code == 403

    def test_a_registered_association_still_wins_over_the_path(
        self, session, scoped_client
    ):
        """
        Inference is last. A file registered to project A but sitting under
        project B's prefix belongs to A -- the record is better evidence than the
        location, and this is the case where they disagree.
        """
        owner = make_project(session, "0055")
        elsewhere = make_project(session, "0056")
        uri = f"s3://test-results-bucket/{elsewhere.project_id}/RNA-Seq/counts.txt"
        f = make_file(session, uri)
        session.add(FileProject(file_id=f.id, project_id=owner.id))
        session.commit()

        # Only the registered owner is restricted; the project named in the path
        # is open. Inference winning would bypass the restriction.
        restrict(session, owner)
        enrol(session, elsewhere, "scoped")   # member of the path's project only
        assert scoped_client.get(URL, params={"path": uri}).status_code == 403

    def test_the_origin_is_recorded_as_path(self, session):
        """
        Access granted by convention rather than by record has to be visible in
        the log, so the proportion can be watched shrinking as pipelines start
        registering their outputs.
        """
        from api.files.scope import scope_for_uri

        project = make_project(session, "0057")
        uri = f"s3://test-results-bucket/{project.project_id}/WES/calls.maf"
        scope = scope_for_uri(session, uri)
        assert scope.project_ids == frozenset({project.id})
        assert scope.origin == "path"

    def test_a_registered_file_with_no_associations_falls_through_to_the_path(
        self, session, scoped_client
    ):
        """A File row with no associations says no more about ownership than no
        File row at all."""
        project = make_project(session, "0058")
        enrol(session, project, "scoped")
        uri = f"s3://test-results-bucket/{project.project_id}/gRNA/counts.txt"
        make_file(session, uri)   # registered, but associated with nothing
        assert scoped_client.get(URL, params={"path": uri}).status_code == 200


class TestAuthenticationIsStillRequired:
    """
    Step 1 of the rule. "Open" means open to platform users, not to the internet.

    Worth an explicit test because it is the one property of the previous model
    kept deliberately, and because the natural way to implement open-by-default --
    return early before consulting anything -- would drop it silently.
    """

    def test_an_anonymous_caller_is_refused_on_an_open_project(
        self, session, unauthenticated_client
    ):
        project = make_project(session, "0060")
        f = make_file(session, "s3://bucket/p60/reads.fastq.gz")
        session.add(FileProject(file_id=f.id, project_id=project.id))
        session.commit()

        r = unauthenticated_client.get(URL, params={"path": f.uri})
        assert r.status_code == 401, (
            "an unrestricted project is open to authenticated users, not to "
            "anonymous ones"
        )

    def test_an_anonymous_caller_is_refused_on_an_unregistered_uri(
        self, session, unauthenticated_client
    ):
        project = make_project(session, "0061")
        uri = f"s3://test-results-bucket/{project.project_id}/RNA-Seq/counts.txt"

        assert unauthenticated_client.get(
            URL, params={"path": uri}
        ).status_code == 401
