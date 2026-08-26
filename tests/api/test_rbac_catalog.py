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

    def test_member_is_contained_in_the_elevated_global_roles(self):
        member = ROLE_DEFINITIONS["member"].permissions
        assert member < ROLE_DEFINITIONS["lab_manager"].permissions
        assert member < ROLE_DEFINITIONS["platform_admin"].permissions

    def test_admin_holds_every_permission(self):
        assert ROLE_DEFINITIONS["admin"].permissions == ALL_PERMISSIONS

    def test_job_update_is_reserved_for_machines_and_platform_admin(self):
        """It writes another user's job status, so no ordinary human role gets it."""
        holders = {n for n, r in ROLE_DEFINITIONS.items()
                   if Permission.JOB_UPDATE in r.permissions}
        assert holders == {"service_account", "platform_admin", "admin"}

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

    def test_member_does_not_hold_file_download(self):
        """
        Reads stay global; downloading does not. This is the one permission the
        distinction rests on, so it is asserted separately from the four above.

        While `member` held file:download globally, the project-scoped check on
        GET /files/download-url was vacuous -- has_in_project short-circuits on a
        global grant, so every authenticated user could download every file in the
        product. Putting it back here silently re-opens that.
        """
        assert Permission.FILE_DOWNLOAD not in ROLE_DEFINITIONS["member"].permissions

    def test_the_cross_project_download_roles_are_a_closed_set(self):
        """
        Global file:download defeats project scoping for whoever holds it, which
        is correct for a cross-project operator and wrong for anyone else. The set
        is small on purpose, so growing it is a reviewed decision.
        """
        holders = {n for n, r in ROLE_DEFINITIONS.items()
                   if Permission.FILE_DOWNLOAD in r.permissions
                   and r.scope == RoleScope.GLOBAL}
        assert holders == {"lab_manager", "auditor", "admin"}


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
