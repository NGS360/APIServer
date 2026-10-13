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
from api.rbac.roles import ROLE_DEFINITIONS


class TestDemuxIsNowPartOfTheUserTier:
    """
    Replaces `TestTheRoleItself`, which pinned the contents of
    `demux_operator` and its relationship to `lab_manager`. Both roles were
    retired in the role collapse (NWP-2213, step 3), so those assertions had
    nothing left to describe.

    The history is worth keeping, because this role's two corrections are the
    reason the collapse happened. It shipped one permission wide and had to be
    widened when ten of its eleven holders turned out to need `run:update` on
    the same flow. It then reached fourteen holders through purely reactive
    grants, none ever refused -- which is what made the argument that a
    permission granted to everyone who asks is not restricted, merely queued.

    What survives is the behaviour: demultiplexing is available to any
    authenticated user, and the route-level tests below exercise that
    unchanged.
    """

    def test_demux_is_in_the_default_role(self):
        from api.rbac.roles import DEFAULT_ROLE_NAME

        member = ROLE_DEFINITIONS[DEFAULT_ROLE_NAME].permissions
        assert Permission.RUN_DEMUX in member
        assert Permission.RUN_UPDATE in member, (
            "the samplesheet write is the other half of the same flow -- "
            "granting demux without it reproduced the 2026-09-11 incident"
        )

    def test_the_role_is_gone(self):
        """
        Pinned so that re-adding it is a deliberate act. A narrow role whose
        permissions are already universal grants nothing and reads as though it
        restricts something.
        """
        assert "demux_operator" not in ROLE_DEFINITIONS
        assert "lab_manager" not in ROLE_DEFINITIONS


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

    def test_the_default_role_now_gets_past_the_guard(
        self, client_with_permissions, run
    ):
        """
        Inverted on 2026-09-28. This test previously asserted the opposite, and
        its docstring read "`member` deliberately does not include it -- demux
        spends compute and deletes run-scoped QC records".

        That description of what demux does is still accurate. What changed is
        who is trusted with it: demux_operator had reached fourteen holders
        through reactive grants and every request had been approved, so the
        permission was already effectively universal with a ticket queue in
        front of it. It is now granted by default instead.

        Kept pointed at the default role rather than deleted, because "what a
        brand-new user can do to a run" is the property worth pinning in either
        direction -- if `member` is ever tightened again, this is the test that
        should fail first.
        """
        from api.rbac.roles import DEFAULT_ROLE_NAME

        member = sorted(
            str(p) for p in ROLE_DEFINITIONS[DEFAULT_ROLE_NAME].permissions
        )
        api = client_with_permissions(member, username="plainmember")
        assert self._submit(api, run).status_code != 403

    def test_run_demux_alone_gets_past_the_guard(
        self, client_with_permissions, run
    ):
        """
        Not asserting success -- submitting a real demux needs workflow config and
        a Batch queue. Asserting the guard allows, which is what the role decides.
        """
        api = client_with_permissions([Permission.RUN_DEMUX], username="demuxer")
        assert self._submit(api, run).status_code != 403
