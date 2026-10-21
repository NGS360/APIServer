""" Test cases for the RBAC permission catalog, role definitions, and seeding """
import re
import pathlib

import pytest
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from api.auth.models import User
from api.rbac.models import GrantSource, ProjectMember, Role, RolePermission, UserRole
from api.rbac.permissions import (
    ALL_PERMISSIONS,
    CATALOG,
    PROJECT_SCOPABLE,
    READ_PERMISSIONS,
    Permission,
    is_valid,
)
from api.rbac.roles import ROLE_DEFINITIONS, RoleScope
from api.rbac.seed import assert_catalog_populated, sync_rbac_catalog


class TestPermissionCatalog:
    """The catalog is the vocabulary every authorization decision draws on."""

    def test_catalog_covers_every_permission(self):
        """A Permission with no CATALOG entry would have no description or risk,
        and would silently break GET /rbac/permissions."""
        assert set(CATALOG) == ALL_PERMISSIONS

    def test_no_catalog_entry_without_a_permission(self):
        assert set(CATALOG) <= ALL_PERMISSIONS

    def test_permission_values_are_resource_colon_action(self):
        for permission in Permission:
            assert re.fullmatch(r"[a-z_]+:[a-z_]+", str(permission)), permission

    def test_catalog_resource_matches_the_permission_prefix(self):
        for permission, spec in CATALOG.items():
            assert spec.resource == str(permission).split(":")[0], permission

    def test_every_permission_has_a_description(self):
        for permission, spec in CATALOG.items():
            assert spec.description.strip(), permission

    def test_risk_values_are_known(self):
        for permission, spec in CATALOG.items():
            assert spec.risk in ("low", "medium", "high", "critical"), permission

    def test_project_scopable_is_derived_from_the_catalog(self):
        assert PROJECT_SCOPABLE == frozenset(
            p for p, s in CATALOG.items() if s.project_scopable
        )

    def test_s3_passthrough_permissions_are_global_only(self):
        """These accept an arbitrary S3 URI, so they cannot be project-scoped
        without a URI-to-project resolver, which does not exist."""
        for permission in (Permission.MANIFEST_READ, Permission.MANIFEST_UPLOAD,
                           Permission.MANIFEST_VALIDATE, Permission.FILE_BROWSE):
            assert not CATALOG[permission].project_scopable, permission

    def test_settings_update_is_critical(self):
        """It controls the bucket URIs and the validation Lambda ARN."""
        assert CATALOG[Permission.SETTING_UPDATE].risk == "critical"

    def test_role_manage_is_critical(self):
        assert CATALOG[Permission.ROLE_MANAGE].risk == "critical"

    def test_is_valid_accepts_catalog_members_and_rejects_others(self):
        assert is_valid("project:read")
        assert not is_valid("project:archive")
        assert not is_valid("settings:update")  # note the plural typo

    def test_read_permissions_are_all_reads(self):
        for permission in READ_PERMISSIONS:
            assert str(permission).split(":")[1].startswith("read")


class TestCatalogMatchesTheDesign:
    """docs/RBAC.md is the reviewed specification; the code must not drift."""

    @staticmethod
    def _doc_permissions():
        doc = pathlib.Path("docs/RBAC.md").read_text()
        rows = re.findall(
            r"^\|\s*`([a-z_]+:[a-z_]+)`\s*\|\s*(G|P)\s*\|\s*\**([a-z]+)\**\s*\|",
            doc, re.M,
        )
        return {p: (scope, risk) for p, scope, risk in rows}

    def test_same_permissions_as_the_document(self):
        documented = self._doc_permissions()
        assert documented, "could not parse the catalog out of docs/RBAC.md"
        assert set(documented) == {str(p) for p in Permission}

    def test_same_scope_as_the_document(self):
        for name, (scope, _risk) in self._doc_permissions().items():
            expected = scope == "P"
            assert CATALOG[Permission(name)].project_scopable is expected, name

    def test_same_risk_as_the_document(self):
        for name, (_scope, risk) in self._doc_permissions().items():
            assert CATALOG[Permission(name)].risk == risk, name


class TestRoleDefinitions:

    def test_the_role_roster_is_pinned(self):
        """
        The exact set of builtin roles, so adding or removing one is a visible,
        deliberate change in review rather than an incidental one.

        This guard was missing until a role was added and no test noticed --
        while route counts have been pinned since Phase 4c. docs/RBAC.md carries
        a rule for when a new global role is justified ("only if it adds a write
        permission on a global resource"), and a rule with nothing asserting it
        is a suggestion.

        If you are here because this failed: the question to answer in the PR is
        whether the persona differs by *which projects* it touches, in which case
        it is project membership and not a global role.
        """
        assert set(ROLE_DEFINITIONS) == {
            # user tier
            "member",
            # administrative
            "admin", "vendor_admin", "workflow_admin",
            # service
            "service_account", "run_registrar", "run_associator", "auditor",
            # project
            "project_viewer", "project_contributor", "project_owner",
        }

    def test_member_now_holds_global_file_download_safely(self):
        """
        Inverted 2026-10-13, and why it is now safe is the whole point.

        This asserted the opposite for a month, on sound reasoning: while the
        restricted-project branch of `require_file_download` was a *permission*
        check, `has_in_project` returned true on a global grant, so a universal
        `file:download` satisfied it for every user -- the feature would have
        looked implemented and done nothing.

        Two changes removed that coupling, and neither of them is this role:

        * the restricted branch now checks **membership** (#461), which a global
          grant cannot satisfy -- that is the entire reason membership was
          chosen over a permission; and
        * an unresolved URI is refused by **location** rather than by privilege
          (#459, #460), so holding the permission no longer reaches arbitrary
          S3.

        The permission has stopped being the protection, so keeping it out of
        `member` stopped buying anything. If either mechanism is reverted this
        test should be inverted back: it is the canary for both.

        Superseded reasoning, kept because it was right at the time:

        `has_in_project` returns true on a *global* grant (api/rbac/resolver.py),
        so a universal `file:download` satisfies the restricted-project branch of
        `require_file_download` for every user -- the feature would look
        implemented and do nothing.

        It is pinned because it is a plausible mistake rather than a far-fetched
        one: an earlier draft of docs/RBAC.md said `member` should regain this
        permission when downloads became open by default. Downloads from an
        unrestricted project consult no permission at all, which is what makes
        them open; the permission is only for restricted projects and for URIs
        that resolve to no project.
        """
        assert Permission.FILE_DOWNLOAD in ROLE_DEFINITIONS["member"].permissions

    def test_service_account_can_both_create_and_update_what_it_writes(self):
        """
        The role held run:update without run:create, and sample:create without
        sample:update. A writeback identity that may change a sample but not
        correct it describes no real workflow -- and both halves were being hit
        in production by two different service accounts.

        Pinned as pairs because the asymmetry is the bug, and it is the kind
        that reads as deliberate minimalism until someone measures the callers.

        Runs are the deliberate exception as of 2026-09-28, which is why the
        pair is gone from this list and asserted separately below. The pairing
        rule assumes one identity does the whole lifecycle of a resource. That
        holds for samples and files, where whoever writes a record also
        corrects it. It does not hold for runs: nine accounts share this role
        for job and result writeback, and exactly one of them registers runs,
        so pairing the verbs meant eight machine identities could create runs
        in order to let one do so.
        """
        sa = ROLE_DEFINITIONS["service_account"].permissions

        for create, update in (
            (Permission.SAMPLE_CREATE, Permission.SAMPLE_UPDATE),
            (Permission.FILE_CREATE, Permission.FILE_UPDATE),
        ):
            assert (create in sa) == (update in sa), (
                f"{create} and {update} should be held together or not at all"
            )

    def test_service_account_is_still_not_a_human_role(self):
        """
        Widening it must not turn it into a general write role. It exists for
        machine writeback, and the permissions that spend money or destroy data
        stay out.
        """
        sa = ROLE_DEFINITIONS["service_account"].permissions

        for excluded in (
            Permission.RUN_DEMUX,            # spends compute, deletes QC records
            Permission.PROJECT_SUBMIT_ACTION,  # spends AWS Batch
            Permission.FILE_DOWNLOAD,        # would bypass project restriction
            Permission.SETTING_UPDATE,
        ):
            assert excluded not in sa

    def test_workflow_admin_covers_every_workflow_permission(self):
        """
        Derived from the catalog, not enumerated, so a new workflow:* permission
        joins it automatically. For a role whose stated scope is "owns the
        workflow catalog outright", silently narrowing when the catalog grows
        would be the bug.
        """
        every_workflow_permission = {
            p for p in Permission if str(p).startswith("workflow:")
        }

        assert ROLE_DEFINITIONS["workflow_admin"].permissions == \
            every_workflow_permission

    def test_every_global_role_beyond_member_adds_a_write(self):
        """
        The justification rule, as an assertion. A global role that adds only
        reads is re-implementing project scoping in the global plane, which is
        what this design exists to avoid. `auditor` is the documented exception:
        read-everything is its entire purpose.
        """
        member = ROLE_DEFINITIONS["member"].permissions
        reads_only = set()
        for name, role in ROLE_DEFINITIONS.items():
            if role.scope is not RoleScope.GLOBAL or name in ("member", "auditor"):
                continue
            added = {str(p) for p in role.permissions - member}
            if added and all(
                p.endswith((":read", ":read_all", ":query")) for p in added
            ):
                reads_only.add(name)
        assert reads_only == set(), (
            f"{sorted(reads_only)} add only read permissions beyond member. "
            f"If the persona differs by which projects it touches, that is "
            f"project membership, not a global role."
        )

    def test_all_referenced_permissions_exist(self):
        for name, role in ROLE_DEFINITIONS.items():
            assert role.permissions <= ALL_PERMISSIONS, name

    def test_project_roles_hold_only_project_scopable_permissions(self):
        """A project role granting a global-only permission cannot be honoured by
        the project plane, so it would be a silent no-op."""
        for name, role in ROLE_DEFINITIONS.items():
            if role.scope is RoleScope.PROJECT:
                assert role.permissions <= PROJECT_SCOPABLE, name

    def test_project_roles_form_a_total_order(self):
        """project_member allows one role per user per project, which is only
        coherent if the roles nest."""
        viewer = ROLE_DEFINITIONS["project_viewer"].permissions
        contributor = ROLE_DEFINITIONS["project_contributor"].permissions
        owner = ROLE_DEFINITIONS["project_owner"].permissions
        assert viewer < contributor < owner

    def test_admin_holds_every_permission(self):
        assert ROLE_DEFINITIONS["admin"].permissions == ALL_PERMISSIONS

    def test_service_account_cannot_manage_roles_or_users(self):
        """A machine identity must never be able to escalate itself."""
        perms = ROLE_DEFINITIONS["service_account"].permissions
        assert Permission.ROLE_MANAGE not in perms
        assert Permission.USER_MANAGE not in perms

    def test_auditor_holds_no_write_permission(self):
        writes = {p for p in ALL_PERMISSIONS
                  if not str(p).split(":")[1].startswith("read")
                  and p not in (Permission.FILE_DOWNLOAD, Permission.SEARCH_QUERY)}
        assert not (ROLE_DEFINITIONS["auditor"].permissions & writes)

    def test_only_admin_grants_the_critical_permissions(self):
        for permission in (Permission.ROLE_MANAGE, Permission.USER_MANAGE):
            holders = {n for n, r in ROLE_DEFINITIONS.items()
                       if permission in r.permissions}
            assert holders == {"admin"}, permission

    def test_member_retains_the_transitional_global_reads(self):
        """These preserve today's read-everything behaviour so that closing writes
        and isolating reads stay separate, independently reversible steps."""
        member = ROLE_DEFINITIONS["member"].permissions
        for permission in (Permission.PROJECT_READ, Permission.SAMPLE_READ,
                           Permission.QCRECORD_READ, Permission.FILE_READ):
            assert permission in member, permission

    def test_what_still_protects_a_restricted_project_is_not_a_permission(self):
        """
        Replaces `test_member_does_not_hold_file_download`, which asserted that
        `member` must not hold the permission. It does now, so the property
        worth pinning is the one that made that safe rather than the absence
        itself.

        `file:download` being universal is harmless precisely because nothing
        consults it to decide a restricted project: that branch asks for a
        `project_member` row, which no role can grant. Were the restriction ever
        expressed as a permission again, a universal `file:download` would
        satisfy it for everybody -- so this asserts the shape of the mechanism,
        not the contents of a role.
        """
        import inspect

        from api.files import routes

        source = inspect.getsource(routes.require_file_download)
        restricted_branch = source[source.index("restricted = _restricted_projects"):]
        assert "is_member_of" in restricted_branch, (
            "the restricted-project branch no longer checks membership; if it "
            "checks a permission again, file:download must leave `member`"
        )
        assert "has_in_project(Permission.FILE_DOWNLOAD" not in restricted_branch


class TestSeeding:

    def test_creates_every_builtin_role(self, session: Session):
        summary = sync_rbac_catalog(session)
        assert summary["roles_created"] == len(ROLE_DEFINITIONS)
        names = {r.name for r in session.exec(select(Role)).all()}
        assert names == set(ROLE_DEFINITIONS)

    def test_marks_seeded_roles_builtin(self, session: Session):
        sync_rbac_catalog(session)
        assert all(r.is_builtin for r in session.exec(select(Role)).all())

    def test_permission_rows_match_the_definitions(self, session: Session):
        sync_rbac_catalog(session)
        for name, definition in ROLE_DEFINITIONS.items():
            role = session.exec(select(Role).where(Role.name == name)).one()
            stored = {
                rp.permission for rp in session.exec(
                    select(RolePermission).where(RolePermission.role_id == role.id)
                ).all()
            }
            assert stored == {str(p) for p in definition.permissions}, name

    def test_is_idempotent(self, session: Session):
        sync_rbac_catalog(session)
        second = sync_rbac_catalog(session)
        assert second == {"roles_created": 0, "roles_updated": 0,
                          "permissions_added": 0, "permissions_removed": 0}

    def test_adds_a_permission_that_appears_in_code(self, session: Session):
        """Simulates a release that widens a builtin role."""
        sync_rbac_catalog(session)
        role = session.exec(select(Role).where(Role.name == "member")).one()
        removed = session.exec(
            select(RolePermission).where(
                RolePermission.role_id == role.id,
                RolePermission.permission == str(Permission.CHAT_USE),
            )
        ).one()
        session.delete(removed)
        session.commit()

        summary = sync_rbac_catalog(session)
        assert summary["permissions_added"] == 1

    def test_removes_a_permission_no_longer_in_code(self, session: Session):
        """A role must not keep a permission the definitions dropped."""
        sync_rbac_catalog(session)
        role = session.exec(select(Role).where(Role.name == "member")).one()
        session.add(RolePermission(role_id=role.id,
                                   permission=str(Permission.SETTING_UPDATE)))
        session.commit()

        summary = sync_rbac_catalog(session)
        assert summary["permissions_removed"] == 1
        remaining = {
            rp.permission for rp in session.exec(
                select(RolePermission).where(RolePermission.role_id == role.id)
            ).all()
        }
        assert str(Permission.SETTING_UPDATE) not in remaining

    def test_leaves_custom_roles_alone(self, session: Session):
        """Admin-created roles are not code-defined and must survive a sync."""
        sync_rbac_catalog(session)
        custom = Role(name="custom_reviewer", display_name="Custom Reviewer",
                      scope=RoleScope.GLOBAL, is_builtin=False)
        session.add(custom)
        session.commit()
        session.add(RolePermission(role_id=custom.id,
                                   permission=str(Permission.PROJECT_READ)))
        session.commit()

        sync_rbac_catalog(session)

        still_there = session.exec(
            select(Role).where(Role.name == "custom_reviewer")
        ).first()
        assert still_there is not None
        assert not still_there.is_builtin
        perms = session.exec(
            select(RolePermission).where(RolePermission.role_id == custom.id)
        ).all()
        assert len(perms) == 1

    def test_never_touches_grants(self, session: Session):
        """Deleting a role would cascade its grants away, silently revoking
        access. Seeding must never do that."""
        sync_rbac_catalog(session)
        user = User(username="grantee", email="g@example.com",
                    is_active=True, is_verified=True)
        session.add(user)
        session.commit()
        role = session.exec(select(Role).where(Role.name == "member")).one()
        session.add(UserRole(user_id=user.id, role_id=role.id,
                             source=GrantSource.MANUAL))
        session.commit()

        sync_rbac_catalog(session)

        grants = session.exec(select(UserRole)).all()
        assert len(grants) == 1
        assert grants[0].user_id == user.id

    def test_updates_display_metadata_from_code(self, session: Session):
        sync_rbac_catalog(session)
        role = session.exec(select(Role).where(Role.name == "member")).one()
        role.display_name = "Stale Name"
        session.add(role)
        session.commit()

        summary = sync_rbac_catalog(session)
        assert summary["roles_updated"] == 1
        refreshed = session.exec(select(Role).where(Role.name == "member")).one()
        assert refreshed.display_name == ROLE_DEFINITIONS["member"].display_name

    def test_assert_catalog_populated_raises_on_empty(self, session: Session):
        """An empty catalog with enforcement on denies every request, so startup
        must fail rather than serve an outage as 403s."""
        with pytest.raises(RuntimeError, match="catalog is empty"):
            assert_catalog_populated(session)

    def test_assert_catalog_populated_passes_after_seeding(self, session: Session):
        sync_rbac_catalog(session)
        assert_catalog_populated(session)


class TestGrantConstraints:
    """Schema-level guarantees the resolver will depend on."""

    def test_a_user_cannot_hold_the_same_global_role_twice(self, session: Session):
        sync_rbac_catalog(session)
        user = User(username="dupe", email="d@example.com",
                    is_active=True, is_verified=True)
        session.add(user)
        session.commit()
        role = session.exec(select(Role).where(Role.name == "member")).one()

        session.add(UserRole(user_id=user.id, role_id=role.id))
        session.commit()
        session.add(UserRole(user_id=user.id, role_id=role.id))
        with pytest.raises(IntegrityError, match="uq_user_role|user_role.user_id"):
            session.commit()
        session.rollback()

    def test_a_user_has_at_most_one_role_per_project(
        self, session: Session, test_project
    ):
        sync_rbac_catalog(session)
        user = User(username="member1", email="m@example.com",
                    is_active=True, is_verified=True)
        session.add(user)
        session.commit()
        viewer = session.exec(select(Role).where(Role.name == "project_viewer")).one()
        owner = session.exec(select(Role).where(Role.name == "project_owner")).one()

        session.add(ProjectMember(project_id=test_project.id, user_id=user.id,
                                  role_id=viewer.id))
        session.commit()
        session.add(ProjectMember(project_id=test_project.id, user_id=user.id,
                                  role_id=owner.id))
        with pytest.raises(IntegrityError,
                           match="uq_project_member|project_member.project_id"):
            session.commit()
        session.rollback()

    def test_grants_default_to_manual_provenance(self, session: Session):
        sync_rbac_catalog(session)
        user = User(username="prov", email="p@example.com",
                    is_active=True, is_verified=True)
        session.add(user)
        session.commit()
        role = session.exec(select(Role).where(Role.name == "member")).one()
        grant = UserRole(user_id=user.id, role_id=role.id)
        session.add(grant)
        session.commit()
        assert grant.source == GrantSource.MANUAL


class TestTheCollapsedRoster:
    """
    The three-tier model, as assertions. Replaces eleven tests that pinned the
    relationships between roles that no longer exist (NWP-2213, step 3).

    What was removed and why: `lab_manager`, `demux_operator`,
    `manifest_operator`, `workflow_publisher` and `platform_admin` are gone, so
    tests like "manifest_operator is narrower than lab_manager" assert nothing.
    The properties worth keeping are not relationships between roles but the
    two boundaries the design actually rests on -- what is reserved, and what
    `member` therefore holds.
    """

    def test_the_reserved_sets_are_exactly_as_designed(self):
        """
        The whole design, in one assertion.

        `member` is derived as the complement of these, so a permission added
        to the catalogue lands in the user tier unless somebody reserves it.
        That is the intended default for a platform whose stance is
        "permissible unless the project is restricted", and it is the reason
        this test exists: adding a permission fails here until someone decides
        which side of the line it belongs on.
        """
        from api.rbac.roles import (_ADMIN_ONLY, _MEMBERSHIP_GATED,
                                    _PROJECT_OWNER_ONLY, _RESERVED,
                                    _VENDOR_ADMIN_ONLY, _WORKFLOW_ADMIN_ONLY)

        assert {str(p) for p in _ADMIN_ONLY} == {
            "role:manage", "user:manage", "setting:update", "system:reindex",
            "project:delete", "job:update",
        }
        assert {str(p) for p in _VENDOR_ADMIN_ONLY} == {
            "vendor:create", "vendor:update", "vendor:delete",
        }
        assert {str(p) for p in _WORKFLOW_ADMIN_ONLY} == {
            "workflow:create", "workflow:update", "workflow:delete",
            "workflow:deploy",
        }
        assert {str(p) for p in _MEMBERSHIP_GATED} == {"project:manage_members"}
        assert {str(p) for p in _PROJECT_OWNER_ONLY} == {"project:restrict"}
        assert len(_RESERVED) == 15

    def test_member_is_everything_not_reserved(self):
        from api.rbac.roles import _RESERVED

        member = ROLE_DEFINITIONS["member"].permissions
        assert member == ALL_PERMISSIONS - _RESERVED
        assert len(member) == len(ALL_PERMISSIONS) - 15 == 43

    def test_admin_still_holds_everything(self):
        assert ROLE_DEFINITIONS["admin"].permissions == ALL_PERMISSIONS

    def test_job_update_is_the_machine_tier_s_alone(self):
        """
        The one permission that kept a service tier from being merged into the
        user tier. It writes *another user's* job status, which cannot be
        expressed as "the owner may update it" because the Batch poller is not
        the owner.
        """
        holders = {n for n, r in ROLE_DEFINITIONS.items()
                   if Permission.JOB_UPDATE in r.permissions}
        assert holders == {"admin", "service_account"}

    def test_the_resource_catalogues_write_surfaces_are_reserved(self):
        for permission, owner in (
            (Permission.VENDOR_CREATE, "vendor_admin"),
            (Permission.VENDOR_UPDATE, "vendor_admin"),
            (Permission.VENDOR_DELETE, "vendor_admin"),
            (Permission.WORKFLOW_CREATE, "workflow_admin"),
            (Permission.WORKFLOW_UPDATE, "workflow_admin"),
            (Permission.WORKFLOW_DEPLOY, "workflow_admin"),
            (Permission.WORKFLOW_DELETE, "workflow_admin"),
        ):
            holders = {n for n, r in ROLE_DEFINITIONS.items()
                       if permission in r.permissions}
            assert holders == {"admin", owner}, permission

    def test_vendor_writes_are_reserved_because_they_move_the_signing_allowlist(
        self
    ):
        """
        Not tidiness. `vendor.bucket` drives which S3 locations the platform
        will sign for (api/files/scope.py), so a user who can write that column
        decides what is signable. With these in `member` the allowlist would be
        user-editable, which is no allowlist.
        """
        member = ROLE_DEFINITIONS["member"].permissions
        assert Permission.VENDOR_CREATE not in member
        assert Permission.VENDOR_UPDATE not in member
        assert Permission.VENDOR_READ in member, "reading the catalogue is fine"

    def test_the_reads_only_role_is_narrower_than_the_user_tier(self):
        """
        `auditor` survived the collapse rather than being folded in, because
        merging it would have *granted* its holder write access to everything
        -- the opposite of what an auditor is.
        """
        auditor = ROLE_DEFINITIONS["auditor"].permissions
        member = ROLE_DEFINITIONS["member"].permissions
        assert auditor < member | {Permission.ROLE_READ}
        writes = {p for p in auditor
                  if not str(p).endswith(":read")
                  and p not in (Permission.FILE_DOWNLOAD, Permission.SEARCH_QUERY,
                                Permission.JOB_READ_ALL)}
        assert not writes

    def test_the_machine_roles_stay_separate_and_narrow(self):
        """
        run:create and run:associate were narrowed out of service_account in
        #447 and #451, on evidence that 16 of 17 accounts holding run:create had
        never registered a run. The collapse does not undo that for machines:
        the two one-permission roles remain, and service_account still does not
        carry either.

        It *does* make them redundant for humans -- both permissions are in
        `member` now, so any authenticated user can register a run. That is the
        stated design ("non-administrative actions are permissible"), and the
        roles persist for the service accounts that hold them, so no grant is
        lost. Recorded here because it is easy to read the surviving roles as
        still restricting something they no longer restrict.
        """
        sa = ROLE_DEFINITIONS["service_account"].permissions
        assert Permission.RUN_CREATE not in sa
        assert Permission.RUN_ASSOCIATE not in sa
        assert ROLE_DEFINITIONS["run_registrar"].permissions == {
            Permission.RUN_CREATE}
        assert ROLE_DEFINITIONS["run_associator"].permissions == {
            Permission.RUN_ASSOCIATE}

        member = ROLE_DEFINITIONS["member"].permissions
        assert Permission.RUN_CREATE in member
        assert Permission.RUN_ASSOCIATE in member

    def test_no_global_role_grants_project_manage_members(self):
        """
        Membership is a restricted project's allowlist, so managing the
        allowlist is checked as "admin, or an existing member" in
        api/rbac/deps.py rather than granted by a role. `admin` holds it only
        because admin holds everything.
        """
        holders = {n for n, r in ROLE_DEFINITIONS.items()
                   if r.scope is RoleScope.GLOBAL
                   and Permission.PROJECT_MANAGE_MEMBERS in r.permissions}
        assert holders == {"admin"}


class TestServiceAccountsCanReachWhatTheyCall:
    """
    Added 2026-10-16, after the final guard batch refused two service accounts.

    The batch checked that every permission it used was in the *default* role,
    which is true and was the wrong check. Service accounts do not hold the
    default role -- they are created with `--role service_account` alone, which
    calls grant_role directly and never goes through assign_default_roles. So a
    permission can be universal among humans and absent from every machine
    account.

    Two routes were affected: GET /jobs/{job_id}, where NGS-Observe was taking a
    real 403 160 times a week because service_account carries job:read_all and
    not job:read; and GET /actions/configs, where the Batch event trigger was
    recorded would_deny 32 times a week. Both were found by auditing API-key
    callers against the guards on the routes they use -- the check that should
    have preceded the batch.
    """

    def test_reading_one_job_accepts_either_job_permission(self):
        """
        `job:read_all` is strictly broader than `job:read`: a caller allowed to
        read every user's jobs is allowed to read one of them. Guarding the
        single-job routes on `job:read` alone made the broader permission
        useless on them, which is how a holder of only `job:read_all` got a 403.
        """
        import inspect

        from api.jobs import routes

        source = inspect.getsource(routes)
        assert source.count(
            'Permission.JOB_READ, Permission.JOB_READ_ALL, mode="any"'
        ) == 3, (
            "the three single-job read routes should accept either permission"
        )

    def test_service_account_holds_what_the_batch_trigger_reads(self):
        sa = ROLE_DEFINITIONS["service_account"].permissions
        assert Permission.ACTION_READ in sa
        assert Permission.JOB_READ_ALL in sa

    def test_service_account_holds_the_ingestion_writes(self):
        """
        Added 2026-10-20 for the NGS360 ingestion account: read project,
        bulk-create samples, validate manifest, patch project. It was taking
        real 403s on PATCH /projects/{project_id} and would_deny on
        POST /manifest/validate.

        Pinned together because they are one flow, and because adding them
        widened the shared role for a single account -- the trade #447 argued
        against. The reasoning is on the role definition; the short version is
        that project:update is project-scopable, so a dedicated global role for
        it would break the documented rule that new global roles are justified
        only for writes on global resources.
        """
        sa = ROLE_DEFINITIONS["service_account"].permissions
        assert Permission.MANIFEST_VALIDATE in sa
        assert Permission.PROJECT_UPDATE in sa

    def test_the_machine_role_still_excludes_what_spends_or_destroys(self):
        """
        The boundary that keeps this role from drifting into a general write
        identity as permissions are added to it one request at a time. Every
        entry here was deliberately kept out, and each addition to the role
        should have to argue with this list.
        """
        sa = ROLE_DEFINITIONS["service_account"].permissions
        for excluded in (
            Permission.RUN_DEMUX,              # spends compute, deletes QC records
            Permission.PROJECT_SUBMIT_ACTION,  # spends AWS Batch
            Permission.PROJECT_INGEST,         # spends compute, writes S3
            Permission.FILE_DOWNLOAD,          # cross-project data egress
            Permission.FILE_BROWSE,
            Permission.PROJECT_DELETE,
            Permission.FILE_DELETE,
            Permission.SAMPLE_DELETE,
            Permission.SETTING_UPDATE,
            Permission.ROLE_MANAGE,
            Permission.USER_MANAGE,
        ):
            assert excluded not in sa, excluded

    def test_a_machine_account_is_not_assumed_to_hold_the_default_role(self):
        """
        The assumption that caused this. Stated as an assertion so that reading
        `member` is never again mistaken for reading what a service account has.
        """
        sa = ROLE_DEFINITIONS["service_account"].permissions
        member = ROLE_DEFINITIONS["member"].permissions
        assert not member <= sa, (
            "service_account is deliberately not a superset of member -- a "
            "permission being universal among humans says nothing about "
            "whether a machine account has it"
        )
