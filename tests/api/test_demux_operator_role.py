"""
The demux_operator role: exactly run:demux, and nothing else.

Demultiplexing was being attempted by eleven different people over one week, with
different jobs and no single team among them. The obvious answer -- give them
lab_manager, the role whose description already says "demultiplexes" -- was wrong,
and the reason is the point of this file:

    lab_manager carries *global* file:download, and AuthzContext.has_in_project
    short-circuits on a global grant. Granting it would have exempted eleven
    people from project-scoped downloads, days after that scoping shipped, as a
    side effect of a decision about demux.

So the role holds one permission. `member` already provides run:read, job:submit
and job:read -- the rest of the demux flow -- which is why one permission is
sufficient rather than merely minimal.
"""
import pytest

from api.rbac.permissions import Permission
from api.rbac.roles import ROLE_DEFINITIONS, RoleScope


class TestTheRoleItself:

    def test_it_holds_exactly_run_demux(self):
        assert ROLE_DEFINITIONS["demux_operator"].permissions == frozenset(
            {Permission.RUN_DEMUX}
        )

    def test_it_is_global(self):
        """A run reaches projects only many-to-many -- a flowcell spans projects --
        so demux cannot be a project-scoped permission."""
        assert ROLE_DEFINITIONS["demux_operator"].scope is RoleScope.GLOBAL

    def test_it_does_not_carry_global_file_download(self):
        """
        The whole reason this role exists instead of lab_manager. has_in_project
        honours a global grant, so global file:download would exempt the holder
        from project-scoped downloads entirely.
        """
        perms = {str(p) for p in ROLE_DEFINITIONS["demux_operator"].permissions}
        assert "file:download" not in perms

    def test_it_is_a_strict_subset_of_lab_manager(self):
        """
        Not an alternative to lab_manager but a slice of it, so someone who
        genuinely is sequencing core still gets demux from lab_manager and nobody
        needs both.
        """
        assert (ROLE_DEFINITIONS["demux_operator"].permissions
                < ROLE_DEFINITIONS["lab_manager"].permissions)

    def test_member_plus_demux_operator_is_enough_for_the_whole_flow(self):
        """
        The claim that makes one permission sufficient: everything else demux
        needs, every user already has.
        """
        member = {str(p) for p in ROLE_DEFINITIONS["member"].permissions}
        demux = {str(p) for p in ROLE_DEFINITIONS["demux_operator"].permissions}
        for needed in ("run:read", "job:submit", "job:read", "run:demux"):
            assert needed in member | demux, needed


class TestItWorksOnTheRoute:

    @pytest.fixture(name="run")
    def run_fixture(self, session):
        from datetime import date

        from api.runs.models import SequencingRun

        r = SequencingRun(run_id="260903_M1_1_FCX", run_date=date(2026, 9, 3),
                          machine_id="M1", run_number="1", flowcell_id="FCX")
        session.add(r)
        session.commit()
        session.refresh(r)
        return r

    def _submit(self, client, run):
        return client.post(
            "/api/v1/runs/demultiplex",
            json={"run_id": run.run_id, "workflow_id": "noop"},
        )

    def test_a_user_without_it_is_refused(self, restricted_client, run):
        response = self._submit(restricted_client, run)
        assert response.status_code == 403
        assert "run:demux" in response.json()["detail"]

    def test_the_default_role_alone_is_refused(self, client_with_permissions, run):
        """`member` deliberately does not include it -- demux spends compute and
        deletes run-scoped QC records."""
        from api.rbac.roles import DEFAULT_ROLE_NAME

        member = sorted(
            str(p) for p in ROLE_DEFINITIONS[DEFAULT_ROLE_NAME].permissions
        )
        api = client_with_permissions(member, username="plainmember")
        assert self._submit(api, run).status_code == 403

    def test_run_demux_alone_gets_past_the_guard(
        self, client_with_permissions, run
    ):
        """
        Not asserting success -- submitting a real demux needs workflow config and
        a Batch queue. Asserting the guard allows, which is what the role decides.
        """
        api = client_with_permissions([Permission.RUN_DEMUX], username="demuxer")
        assert self._submit(api, run).status_code != 403
