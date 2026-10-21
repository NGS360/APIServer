"""
Builtin role definitions.

Roles live in the database so administrators can compose custom ones, but the
*builtin* roles' permission sets are declared here and re-derived on every deploy
by `sync_rbac_catalog()`. Adding a permission to a builtin role is therefore a
reviewable code change rather than an undocumented database edit.

The rule for adding a new global role: it is justified only if it grants a write
on a global (non-project) resource. Personas that differ only in *which projects*
they touch are already expressed by project membership -- adding a global role
per persona re-implements project scoping in the global plane, which is what this
design exists to avoid. Variants like "contributor without delete" are served by
custom roles, which is why roles are rows.

See docs/RBAC.md for the full rationale.
"""

from dataclasses import dataclass
from enum import Enum

from api.rbac.permissions import (
    ALL_PERMISSIONS,
    PROJECT_SCOPABLE,
    READ_PERMISSIONS,
    Permission,
)


class RoleScope(str, Enum):
    """Which plane a role may be granted in."""

    GLOBAL = "global"
    PROJECT = "project"


@dataclass(frozen=True)
class RoleDefinition:
    scope: RoleScope
    display_name: str
    description: str
    permissions: frozenset[Permission]


# --- Global roles ---------------------------------------------------------
#
# Collapsed to three tiers on 2026-10-13 (NWP-2213, step 3). What came before
# was eleven global roles, five of them created reactively over two weeks, and
# every grant request ever made was approved. A permission granted to everyone
# who asks is not a restricted permission; it is an unrestricted one with a
# ticket queue in front of it.
#
# The measurement that settled it: of 44 refusals on project:submit_action over
# 28 days, *all 44* came from callers with no membership of the target project,
# and no project member was ever refused. Repeatedly, the role model turned out
# to be a poor predictor of who needs what -- so the only boundaries kept are
# the two that can be stated confidently:
#
#   * administrative actions, and the two resource catalogues; and
#   * projects explicitly locked down, which is membership, not permission.
#
# The reserved sets below are therefore the whole design. Everything not
# reserved is in `member`.

#: Administrative capability. Held by `admin` alone.
#:
#: job:update is here because it writes *another user's* job status -- the
#: documented reason a machine role exists separately, and the one permission no
#: human tier should hold. project:delete is here because with 11,168 projects
#: and every user able to delete, one mistake is unrecoverable; the other three
#: deletes (file, sample, qcrecord) are in `member` by decision.
_ADMIN_ONLY = frozenset({
    Permission.ROLE_MANAGE,
    Permission.USER_MANAGE,
    Permission.SETTING_UPDATE,
    Permission.SYSTEM_REINDEX,
    Permission.PROJECT_DELETE,
    Permission.JOB_UPDATE,
})

#: The vendor catalogue's write surface.
#:
#: This is reserved for a reason beyond tidiness, and the reason is load-bearing:
#: `vendor.bucket` drives the presigned-URL allowlist (api/files/scope.py), so
#: whoever can write that column decides what the platform will sign. With these
#: in `member`, any authenticated user could register a vendor pointing at an
#: arbitrary bucket and make it signable. The allowlist would be user-editable,
#: which is no allowlist at all.
_VENDOR_ADMIN_ONLY = frozenset({
    Permission.VENDOR_CREATE,
    Permission.VENDOR_UPDATE,
    Permission.VENDOR_DELETE,
})

#: The workflow catalogue's write surface. Reserved on measurement rather than
#: principle: over 28 days exactly three principals wrote workflows, one of them
#: an administrator. Reads are much broader and stay in `member`.
_WORKFLOW_ADMIN_ONLY = frozenset({
    Permission.WORKFLOW_CREATE,
    Permission.WORKFLOW_UPDATE,
    Permission.WORKFLOW_DELETE,
    Permission.WORKFLOW_DEPLOY,
})

#: Not granted to any global role. Membership *is* a restricted project's
#: allowlist, so managing the allowlist is checked as "admin, or an existing
#: member of that project" in api/rbac/deps.py rather than through a role. It is
#: also the exemption that keeps `restricted` from being a one-way door -- see
#: docs/RBAC.md, "The restriction flag was unsettable, and the gate was
#: advisory".
_MEMBERSHIP_GATED = frozenset({
    Permission.PROJECT_MANAGE_MEMBERS,
})

#: Not granted to any *global* role below `admin`, but carried by the project
#: role a creator receives, so the holders are exactly "administrators and the
#: people who made the project".
#:
#: Reserved because it was not, and that was a hole. `restricted` is set through
#: PUT/PATCH /projects/{id}, which is guarded on `project:update` -- a `member`
#: permission -- so until this existed any of the authenticated users could lock
#: any project, including one they had nothing to do with. Worse, locking it was
#: close to irreversible for them: once `restricted` is true the membership gate
#: applies, and unlocking requires being a member, so an accidental flip on
#: somebody else's project had to be undone by an administrator.
#:
#: Note this is a *narrower* grant than `project:update` on the same route, which
#: is the point: editing a project's metadata is ordinary work, changing who can
#: see it at all is not.
_PROJECT_OWNER_ONLY = frozenset({
    Permission.PROJECT_RESTRICT,
})

_RESERVED = (
    _ADMIN_ONLY | _VENDOR_ADMIN_ONLY | _WORKFLOW_ADMIN_ONLY | _MEMBERSHIP_GATED
    | _PROJECT_OWNER_ONLY
)

# The default role, and now the only one an ordinary user needs: everything that
# is not reserved above.
#
# Derived as a complement rather than listed, which is a deliberate trade. It
# means a permission added to the catalogue lands in `member` unless somebody
# reserves it -- the right default for a platform whose stance is "permissible
# unless the project is restricted", and the wrong one to leave unwatched. So
# tests/api/test_rbac_catalog.py pins both the reserved sets and `member`'s
# size: adding a permission fails the suite until someone decides which side of
# the line it belongs on.
_MEMBER = ALL_PERMISSIONS - _RESERVED

# Machine writeback only: pipeline results and Batch job-status updates. Kept
# separate from the user tier after the collapse, because job:update writes
# another user's job status -- which cannot be expressed as "the owner may
# update it", since the Batch poller is not the owner.
#
# Deliberately *not* merged into one fat service role. run:create and
# run:associate were narrowed out of it in #447 and #451 on evidence that 16 of
# 17 accounts holding run:create had never registered a run; folding them back
# would undo that.
_SERVICE_ACCOUNT = frozenset({
    Permission.PROJECT_READ,
    Permission.RUN_READ,
    Permission.RUN_UPDATE,
    Permission.SAMPLE_READ,
    Permission.SAMPLE_CREATE,
    Permission.SAMPLE_UPDATE,
    Permission.QCRECORD_CREATE,
    Permission.FILE_CREATE,
    Permission.FILE_UPDATE,
    Permission.JOB_READ_ALL,
    Permission.JOB_UPDATE,
    Permission.WORKFLOW_READ,
    # Added 2026-10-16. GET /actions/configs was guarded in the final batch and
    # the Batch event trigger reads it 32 times a week to dispatch jobs -- it had
    # no action:read, so the guard recorded would_deny. Caught by auditing every
    # API-key caller against the guards on the routes they use, which is the
    # check that should have preceded the batch rather than followed it.
    Permission.ACTION_READ,
    # Added 2026-10-20 for the NGS360 ingestion account, whose measured flow is
    # read project -> bulk-create samples -> validate manifest -> patch project.
    # It was taking real 403s on PATCH /projects/{project_id} and would_deny on
    # POST /manifest/validate.
    #
    # This widens the shared role for one account, which is the trade #447
    # argued against when it took run:create *out* of here on the evidence that
    # 16 of 17 holders had never used it. The reasoning for going the other way:
    #
    #   * project:update is project-scopable, and the documented rule above
    #     says a new global role is justified only for a write on a *global*
    #     resource. A role carrying project:update would break that rule --
    #     project-scoped personas belong in project membership.
    #   * service_account already carries six project-scopable writes globally
    #     (sample:create, sample:update, file:create, file:update,
    #     qcrecord:create, project:read) for the documented reason that a machine
    #     cannot be enrolled in every project whose data it writes. project:update
    #     is the same shape as those, not a new kind of grant.
    #   * the role model was collapsed from eleven global roles to six four days
    #     ago, specifically to stop one-account roles accumulating. An eighth
    #     one a week later would undo that.
    #
    # The cost is real and worth naming: the other eight service accounts gain
    # two permissions they do not use. If a second account ever needs
    # project:update on a *specific* set of projects rather than all of them,
    # the right answer is enrolling it per project, not widening this further.
    Permission.MANIFEST_VALIDATE,
    Permission.PROJECT_UPDATE,
})

# `run_registrar` used to be defined here, carrying run:create alone. See #447:
# over 2026-08-18..09-28 exactly two principals called POST /runs -- a service
# account that still does it daily, and an administrator's personal key doing
# the same job by hand, since revoked.
#
# Converted to a custom role on 2026-10-21. It is now an ordinary database row
# that administrators own through /rbac/roles, not a code-defined one, and
# sync_rbac_catalog() leaves it alone. Nothing about what it grants changed; what
# changed is who may change it.
#
# Why this one and not the others: a builtin role is the right shape for a
# *persona* the product asserts -- `member`, `admin`, `service_account` all
# describe a kind of caller, and re-deriving them on deploy is what keeps the
# code the source of truth. This was never that. It is one permission held by one
# machine account, which makes it an operational grant, and operational grants
# should be editable by the people running the platform without a deploy. Being
# builtin actively got in the way: update_role_permissions() and delete_role()
# both refuse a builtin outright, so adjusting it meant a PR.
#
# The reasoning in #447 is unaffected -- run:create still does not belong in
# service_account, and the measurement that established that still stands.

# Sample/run association, likewise one service's job. See #451: the metrics
# lambda, refused on all 64 attempts, plus one administrator's personal key.
_RUN_ASSOCIATOR = frozenset({
    Permission.RUN_ASSOCIATE,
})

# Read-only across the platform, for compliance, QA and read-only agents. Kept
# through the collapse rather than folded into `member`: it is narrower than the
# user tier, not wider, and merging it would have *granted* its holder write
# access to everything -- the opposite of what an auditor is.
_AUDITOR = READ_PERMISSIONS | {
    Permission.FILE_DOWNLOAD,
    Permission.SEARCH_QUERY,
    Permission.ROLE_READ,
}

# The vendor catalogue's owner. Narrow by construction -- `vendor:read` stays in
# `member`, so this is the write surface and nothing else.
_VENDOR_ADMIN = frozenset(_VENDOR_ADMIN_ONLY | {Permission.VENDOR_READ})

# The workflow catalogue's owner. Derived from the catalogue rather than listed,
# so a new workflow:* permission joins it automatically; for this role that is
# the intent, since "owns the workflow catalogue outright" should not silently
# narrow when the catalogue grows.
_WORKFLOW_ADMIN = frozenset(
    p for p in Permission if str(p).startswith("workflow:")
)

# --- Project roles --------------------------------------------------------
# A total order: viewer subset of contributor subset of owner. That is why
# project_member allows only one role per user per project -- stacking them would
# add nothing but ambiguity in the UI.

_PROJECT_VIEWER = frozenset({
    Permission.PROJECT_READ,
    Permission.SAMPLE_READ,
    Permission.QCRECORD_READ,
    Permission.FILE_READ,
    Permission.FILE_DOWNLOAD,
})

_PROJECT_CONTRIBUTOR = _PROJECT_VIEWER | {
    Permission.PROJECT_UPDATE,
    Permission.SAMPLE_CREATE,
    Permission.SAMPLE_UPDATE,
    Permission.SAMPLE_DELETE,
    Permission.QCRECORD_CREATE,
    Permission.QCRECORD_DELETE,
    Permission.FILE_CREATE,
    Permission.FILE_UPDATE,
    Permission.FILE_DELETE,
    Permission.PROJECT_SUBMIT_ACTION,
    Permission.PROJECT_INGEST,
}

_PROJECT_OWNER = _PROJECT_CONTRIBUTOR | {
    Permission.PROJECT_MANAGE_MEMBERS,
    Permission.PROJECT_DELETE,
    Permission.PROJECT_RESTRICT,
}


ROLE_DEFINITIONS: dict[str, RoleDefinition] = {
    # --- the user tier ---
    "member": RoleDefinition(
        RoleScope.GLOBAL, "Member",
        "Default for every authenticated user: everything that is not "
        "administrative, a resource catalogue's write surface, or gated on "
        "project membership.",
        frozenset(_MEMBER),
    ),
    # --- administrative ---
    "admin": RoleDefinition(
        RoleScope.GLOBAL, "Administrator",
        "Every permission. Recomputed on each sync, so new permissions are included.",
        ALL_PERMISSIONS,
    ),
    "vendor_admin": RoleDefinition(
        RoleScope.GLOBAL, "Vendor Administrator",
        "Owns the vendor catalogue. Load-bearing beyond tidiness: vendor.bucket "
        "drives the presigned-URL allowlist, so this is who may decide what the "
        "platform will sign.",
        frozenset(_VENDOR_ADMIN),
    ),
    "workflow_admin": RoleDefinition(
        RoleScope.GLOBAL, "Workflow Administrator",
        "Owns the workflow catalogue outright, including deletion.",
        frozenset(_WORKFLOW_ADMIN),
    ),
    # --- service roles ---
    "service_account": RoleDefinition(
        RoleScope.GLOBAL, "Service Account",
        "Machine writeback for pipeline results and Batch job status. Not for humans.",
        frozenset(_SERVICE_ACCOUNT),
    ),
    # No "run_registrar" here on purpose -- it is a custom role now, owned by
    # administrators rather than by this file. See the note above _RUN_ASSOCIATOR
    # and migration c8e4a1f72b93. Re-adding it here would take it back off them:
    # sync_rbac_catalog() forces is_builtin=True on every role it defines, so the
    # row would silently become uneditable again at the next startup.
    "run_associator": RoleDefinition(
        RoleScope.GLOBAL, "Run Associator",
        "May associate and dissociate samples and runs. Grants nothing else -- "
        "see the comment on _RUN_ASSOCIATOR for why this is not service_account.",
        frozenset(_RUN_ASSOCIATOR),
    ),
    "auditor": RoleDefinition(
        RoleScope.GLOBAL, "Auditor",
        "Read-only across the platform, for compliance, QA and read-only agents. "
        "Narrower than `member`, not wider -- which is why it survived the "
        "collapse rather than being folded in.",
        frozenset(_AUDITOR),
    ),
    # --- project roles ---
    "project_viewer": RoleDefinition(
        RoleScope.PROJECT, "Project Viewer",
        "See a project's data.",
        frozenset(_PROJECT_VIEWER),
    ),
    "project_contributor": RoleDefinition(
        RoleScope.PROJECT, "Project Contributor",
        "See and change a project's data, and submit work for it.",
        frozenset(_PROJECT_CONTRIBUTOR),
    ),
    "project_owner": RoleDefinition(
        RoleScope.PROJECT, "Project Owner",
        "Full control of a project, including its membership.",
        frozenset(_PROJECT_OWNER),
    ),
}

# The role granted to every new user unless DEFAULT_USER_ROLE says otherwise.
DEFAULT_ROLE_NAME = "member"

# The role a project's creator receives, granted in the same transaction as the
# project insert -- otherwise a user creates a project they cannot administer.
PROJECT_CREATOR_ROLE_NAME = "project_owner"


def _validate_definitions() -> None:
    """
    Fail at import if a definition is inconsistent.

    Cheap to run and catches the mistakes that would otherwise surface as a
    permission that silently does nothing, or a project role granting something
    the project plane cannot express.
    """
    for name, role in ROLE_DEFINITIONS.items():
        unknown = role.permissions - ALL_PERMISSIONS
        if unknown:
            raise ValueError(f"role {name!r} references unknown permissions: {unknown}")
        if role.scope is RoleScope.PROJECT:
            not_scopable = role.permissions - PROJECT_SCOPABLE
            if not_scopable:
                raise ValueError(
                    f"project-scoped role {name!r} contains global-only "
                    f"permissions: {sorted(not_scopable)}"
                )


_validate_definitions()
