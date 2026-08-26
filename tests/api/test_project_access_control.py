"""
Project-level access control: membership of one project must not confer access
to another.

`tests/api/test_rbac_route_guards.py` already proves that a project role grants
access to *its* project and that a user with no roles is refused. Neither of those
catches the failure that matters most here: a guard that checks "does this user
hold the permission anywhere" rather than "in this project" passes both of those
tests while providing no isolation at all. That is what this file exists to catch,
so every write test below is paired — the same call, the same role, a different
project.

What these tests establish, and it is worth stating precisely because the two
halves differ:

* **Writes and actions are project-scoped today.** `member` — which every user
  holds via the bootstrap backfill — carries no global `sample:create`,
  `project:update`, `project:ingest`, `project:submit_action` or
  `project:manage_members`. So the project plane is the only way to obtain them,
  and non-members are genuinely refused.
* **Reads are not, by decision.** `member` carries global `project:read`,
  `sample:read`, `file:read` and `qcrecord:read`, and `has_in_project`
  short-circuits on a global grant, so those reach every project. That is the
  transitional choice recorded in docs/RBAC.md and is being kept.
* **Downloads are scoped.** `file:download` was removed from `member` for exactly
  the reason above — while it was there the project check on
  `GET /files/download-url` was vacuous. See
  tests/api/test_file_download_scope.py.

A failed permission check is a 403, here and in production.
"""
import pytest
from sqlmodel import select

from api.auth.models import User
from api.project.models import Project
from api.rbac.models import GrantSource, ProjectMember, Role


def make_project(session, project_id: str, name: str) -> Project:
    project = Project(project_id=project_id, name=name, created_by="testuser")
    session.add(project)
    session.commit()
    session.refresh(project)
    return project


def grant_project_role(session, project: Project, username: str, role_name: str):
    user = session.exec(select(User).where(User.username == username)).one()
    role = session.exec(select(Role).where(Role.name == role_name)).one()
    session.add(ProjectMember(project_id=project.id, user_id=user.id,
                              role_id=role.id, source=GrantSource.MANUAL))
    session.commit()


@pytest.fixture(name="mine")
def mine_fixture(session):
    """The project the caller is a member of."""
    return make_project(session, "P-20260101-0001", "Mine")


@pytest.fixture(name="theirs")
def theirs_fixture(session):
    """A project the caller has no relationship to whatsoever."""
    return make_project(session, "P-20260101-0002", "Theirs")


@pytest.fixture(name="contributor")
def contributor_fixture(session, restricted_client, mine):
    """
    `restricted_client` is an authenticated user holding no global roles, made a
    contributor on `mine` only. That combination is the whole point: any access it
    demonstrates has to have come from the project plane.
    """
    grant_project_role(session, mine, "norole", "project_contributor")
    return restricted_client


class TestWritesAreScopedToTheProject:
    """The core requirement, tested in pairs."""

    def test_a_contributor_can_add_a_sample_to_their_own_project(
        self, contributor, mine
    ):
        response = contributor.post(
            f"/api/v1/projects/{mine.project_id}/samples", json={"sample_id": "S-1"}
        )
        assert response.status_code in (200, 201)

    def test_the_same_contributor_cannot_add_a_sample_to_another_project(
        self, contributor, theirs
    ):
        """
        The isolation test. A guard asking "does this user hold sample:create at
        all" would pass the previous test and this one too, and provide no
        isolation whatsoever.
        """
        response = contributor.post(
            f"/api/v1/projects/{theirs.project_id}/samples", json={"sample_id": "S-2"}
        )
        assert response.status_code == 403
        assert "sample:create" in response.json()["detail"]
        assert theirs.project_id in response.json()["detail"]

    def test_a_contributor_can_submit_an_action_on_their_own_project(
        self, contributor, mine
    ):
        """
        Asserting not-refused rather than success: the action needs more setup than
        a permission test should carry. A 422 here means the guard allowed and the
        request reached body validation, which is exactly the distinction a
        permission guard makes -- and the paired test below shows the same call
        stopping at 403 on a project the user is not a member of.
        """
        response = contributor.post(
            f"/api/v1/projects/{mine.project_id}/actions/submit",
            json={"action_name": "noop", "arguments": {}},
        )
        assert response.status_code != 403

    def test_the_same_contributor_cannot_submit_an_action_on_another_project(
        self, contributor, theirs
    ):
        response = contributor.post(
            f"/api/v1/projects/{theirs.project_id}/actions/submit",
            json={"action_name": "noop", "arguments": {}},
        )
        assert response.status_code == 403
        assert "project:submit_action" in response.json()["detail"]

    def test_a_contributor_can_ingest_into_their_own_project(self, contributor, mine):
        response = contributor.post(f"/api/v1/projects/{mine.project_id}/ingest",
                                    json={})
        assert response.status_code != 403

    def test_the_same_contributor_cannot_ingest_into_another_project(
        self, contributor, theirs
    ):
        response = contributor.post(f"/api/v1/projects/{theirs.project_id}/ingest",
                                    json={})
        assert response.status_code == 403
        assert "project:ingest" in response.json()["detail"]


class TestNonMembersAreRefused:
    """A user with no global roles and no membership anywhere."""

    @pytest.mark.parametrize("method,path,body", [
        ("post", "samples", {"sample_id": "S-9"}),
        ("post", "ingest", {}),
        ("post", "actions/submit", {"action_name": "noop", "arguments": {}}),
        ("post", "members", {"username": "someone", "role": "project_viewer"}),
    ])
    def test_a_non_member_cannot_write(
        self, restricted_client, mine, method, path, body
    ):
        response = getattr(restricted_client, method)(
            f"/api/v1/projects/{mine.project_id}/{path}", json=body
        )
        assert response.status_code == 403


class TestTheProjectRolesAreOrdered:
    """project_viewer subset-of project_contributor subset-of project_owner."""

    def test_a_viewer_cannot_write_to_their_own_project(
        self, session, restricted_client, mine
    ):
        grant_project_role(session, mine, "norole", "project_viewer")
        response = restricted_client.post(
            f"/api/v1/projects/{mine.project_id}/samples", json={"sample_id": "S-3"}
        )
        assert response.status_code == 403
        assert "sample:create" in response.json()["detail"]

    def test_a_contributor_cannot_manage_members(self, contributor, mine):
        """
        Membership management is the owner's alone: a contributor able to add
        members could grant itself ownership, which makes the ordering
        decorative.
        """
        response = contributor.post(
            f"/api/v1/projects/{mine.project_id}/members",
            json={"username": "someone", "role": "project_owner"},
        )
        assert response.status_code == 403
        assert "project:manage_members" in response.json()["detail"]

    def test_an_owner_can_manage_its_own_project(
        self, session, restricted_client, mine
    ):
        """
        The self-serve case the project plane exists for.

        This was the one place a project role did not get what it granted. The
        membership routes carried the project guard **and** a `CurrentSuperuser`
        dependency, so the guard allowed -- the access log recorded
        `rbac_decision: allow` with `scope: project <id>` -- and the superuser
        check then refused, leaving an owner unable to see their own members.

        That was defensible only while a guard merely logged: dropping the
        dependency then would have removed the gate rather than moved it, opening
        membership to every authenticated caller. Enforcement is unconditional
        now, so the guard *is* the gate and the dependency is gone -- a panel
        gated on a flag cannot serve a role-based model. `restricted_client`
        holds no global role whatsoever, so the project grant is doing all the
        work here.

        This test was written as the negative assertion with a note saying it
        should become this one when the gate came off. It has.
        """
        grant_project_role(session, mine, "norole", "project_owner")
        response = restricted_client.get(
            f"/api/v1/projects/{mine.project_id}/members"
        )
        assert response.status_code == 200

    def test_a_superuser_can_manage_members(self, superuser_client, session):
        """The counterpart: the gate above is satisfiable, just not by a role."""
        project = make_project(session, "P-20260101-0004", "Superuser view")
        response = superuser_client.get(
            f"/api/v1/projects/{project.project_id}/members"
        )
        assert response.status_code == 200

    def test_an_owner_of_one_project_cannot_manage_members_of_another(
        self, session, restricted_client, mine, theirs
    ):
        grant_project_role(session, mine, "norole", "project_owner")
        response = restricted_client.get(
            f"/api/v1/projects/{theirs.project_id}/members"
        )
        assert response.status_code == 403


class TestAMissingProjectIsNotADisclosure:

    def test_an_unknown_project_is_404_before_any_permission_check(
        self, restricted_client
    ):
        """
        ProjectDep resolves first by design. Answering 403 for a project that does
        not exist tells an unauthorised caller which project ids are real.
        """
        response = restricted_client.post(
            "/api/v1/projects/P-00000000-0000/samples", json={"sample_id": "S-4"}
        )
        assert response.status_code == 404


class TestReadsRemainGlobalByDecision:
    """
    Reads stay global; downloads do not. That split is a decision, not an
    accident, so both halves are pinned.

    `member` keeps global project:read, sample:read, qcrecord:read and file:read,
    which preserves the pre-RBAC "any authenticated user can read anything"
    behaviour. It no longer keeps file:download -- see
    tests/api/test_file_download_scope.py for what replaced it.
    """

    def test_a_global_read_reaches_a_project_the_user_is_not_a_member_of(
        self, client_with_permissions, session
    ):
        from api.rbac.permissions import Permission

        project = make_project(session, "P-20260101-0003", "Not theirs")
        api = client_with_permissions([Permission.SAMPLE_READ], username="reader")
        response = api.get(f"/api/v1/projects/{project.project_id}/samples")
        assert response.status_code == 200, (
            "global sample:read no longer reaches every project -- if that was "
            "deliberate, this test should be inverted, not deleted"
        )

    def test_member_keeps_exactly_the_four_transitional_reads(self):
        """
        The list, as an assertion. Shrinking it is how reads would become
        project-scoped too, and it should be a one-line reviewed change rather
        than a surprise.
        """
        from api.rbac.permissions import PROJECT_SCOPABLE
        from api.rbac.roles import ROLE_DEFINITIONS

        member = {str(p) for p in ROLE_DEFINITIONS["member"].permissions}
        scopable = {str(p) for p in PROJECT_SCOPABLE}
        assert member & scopable == {
            "project:read", "sample:read", "qcrecord:read", "file:read",
        }

    def test_download_is_not_among_them(self):
        """
        Stated separately because it is the one permission the project/global
        split rests on. Putting it back re-opens every file in the product to
        every authenticated user, and does so silently: the guard stays in place
        and simply stops refusing anything.
        """
        from api.rbac.roles import ROLE_DEFINITIONS

        member = {str(p) for p in ROLE_DEFINITIONS["member"].permissions}
        assert "file:download" not in member
