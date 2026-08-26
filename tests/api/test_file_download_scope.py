"""
Project-scoped downloads: may this caller download *this* file?

Until now `GET /files/download-url` was guarded on the global plane, and `member`
held `file:download`, so every authenticated user could download every file in the
product by URI. The parameter is a URI rather than a project id, so scoping it
requires resolving the URI to a project first — api/files/scope.py does that.

The policy under test, decided deliberately:

* **Project-associated files are strict.** A file associated with a project, or
  with a sample (which belongs to exactly one project), resolves to those projects
  and no others.
* **Run-associated files are permissive.** A file with no project or sample
  association but attached to a sequencing run resolves to *every* project that run
  touches. A flowcell is a shared artifact — demux statistics and samplesheets
  belong to the run, not to one project — and the alternative generates a grant
  request per person per flowcell.
* **The order between them is the policy, not an implementation detail.** A file
  that is both in a project and on a run resolves strictly. The test for that is
  the one that catches the permissive path quietly swallowing the strict one.
* **A URI resolving to nothing falls back to the global permission.** `member`
  does not hold it, so an ordinary user cannot download a file belonging to
  nothing; lab_manager, auditor, admin and superusers do, so operating over raw
  storage still works.

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

    def test_a_non_member_cannot(self, session, scoped_client):
        """The requirement, stated minimally."""
        project = make_project(session, "0002")
        f = make_file(session, "s3://bucket/p2/reads.fastq.gz")
        session.add(FileProject(file_id=f.id, project_id=project.id))
        session.commit()

        r = scoped_client.get(URL, params={"path": f.uri})
        assert r.status_code == 403
        assert "file:download" in r.json()["detail"]

    def test_membership_of_a_different_project_does_not_help(
        self, session, scoped_client
    ):
        """
        The isolation case. A check that asked "does this user hold file:download
        anywhere" would pass the first test here and this one too.
        """
        mine = make_project(session, "0003")
        theirs = make_project(session, "0004")
        f = make_file(session, "s3://bucket/p4/reads.fastq.gz")
        session.add(FileProject(file_id=f.id, project_id=theirs.id))
        session.commit()
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

    def test_a_member_of_no_project_on_the_run_still_cannot(
        self, session, scoped_client
    ):
        """Permissive is not open: it widens to the run's projects, not to everyone."""
        on_run = make_project(session, "0012")
        elsewhere = make_project(session, "0013")
        run = make_run(session, "260201_M1_2_FC2")
        put_sample_on_run(session, on_run, run, "S-C")

        f = make_file(session, "s3://bucket/runs/FC2/demux_stats.csv")
        session.add(FileSequencingRun(file_id=f.id, sequencing_run_id=run.id))
        session.commit()

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


class TestTheOldRouteIsTheBypass:
    """
    The control is only as good as the closure of the route beside it.

    `GET /files/download` answers the same question with no guard at all, so while
    it stays open every refusal above is walkable around by changing the URL. It
    stays open because a compute fleet still calls it; this test is here so the
    dependency is visible in CI rather than only in a review conversation.

    When that route closes, invert this test.
    """

    def test_the_unguarded_route_still_serves_what_the_guarded_one_refuses(
        self, session, scoped_client
    ):
        project = make_project(session, "0020")
        f = make_file(session, "s3://bucket/p20/reads.fastq.gz")
        session.add(FileProject(file_id=f.id, project_id=project.id))
        session.commit()

        assert scoped_client.get(URL, params={"path": f.uri}).status_code == 403
        bypass = scoped_client.get("/api/v1/files/download", params={"path": f.uri},
                                   follow_redirects=False)
        assert bypass.status_code == 307, (
            "GET /files/download appears to be guarded now -- if so, project-scoped "
            "downloads are no longer bypassable and this test should assert 403"
        )


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
