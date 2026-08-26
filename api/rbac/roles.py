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

# The default role. Deliberately harmless: it reads catalogs and creates its own
# projects. The five project-scopable reads at the end are transitional -- they
# preserve today's "any authenticated user can read anything" behaviour so that
# closing writes and isolating reads are separate, independently reversible
# steps. Tightening later is a role edit through the admin API, not a deploy.
_MEMBER = frozenset({
    Permission.ACTION_READ,
    Permission.PLATFORM_READ,
    Permission.VENDOR_READ,
    Permission.WORKFLOW_READ,
    Permission.PIPELINE_READ,
    Permission.RUN_READ,
    Permission.JOB_READ,
    Permission.JOB_SUBMIT,
    Permission.SETTING_READ,
    Permission.SEARCH_QUERY,
    Permission.CHAT_USE,
    Permission.USER_READ,
    Permission.PROJECT_CREATE,
    # Transitional global reads -- see above.
    Permission.PROJECT_READ,
    Permission.SAMPLE_READ,
    Permission.QCRECORD_READ,
    Permission.FILE_READ,
    # file:download is deliberately NOT here. Reads stay global; downloading is
    # project-scoped, and while `member` held this globally the project check was
    # vacuous -- has_in_project short-circuits on a global grant, so every
    # authenticated user could download every file in the product. The project
    # roles carry it instead, and api/files/scope.py resolves a URI to the
    # projects whose membership applies.
})

_LAB_MANAGER = _MEMBER | {
    # Restored explicitly after file:download left _MEMBER. The sequencing core
    # works across flowcells, and the permissive run path still requires
    # membership of *some* project the run touches -- which a core operator who
    # is enrolled in no projects does not have. Without this they could browse
    # and upload but not download, which is not a coherent role.
    Permission.FILE_DOWNLOAD,
    Permission.RUN_CREATE,
    Permission.RUN_UPDATE,
    Permission.RUN_ASSOCIATE,
    Permission.RUN_DEMUX,
    Permission.MANIFEST_READ,
    Permission.MANIFEST_UPLOAD,
    Permission.MANIFEST_VALIDATE,
    Permission.FILE_BROWSE,
    Permission.FILE_CREATE,
    Permission.FILE_UPDATE,
    Permission.SAMPLE_CREATE,
    Permission.SAMPLE_UPDATE,
    Permission.QCRECORD_CREATE,
    Permission.PROJECT_INGEST,
    Permission.JOB_READ_ALL,
}

_PLATFORM_ADMIN = _MEMBER | {
    Permission.PLATFORM_CREATE,
    Permission.VENDOR_CREATE,
    Permission.VENDOR_UPDATE,
    Permission.VENDOR_DELETE,
    Permission.WORKFLOW_CREATE,
    Permission.WORKFLOW_UPDATE,
    Permission.WORKFLOW_DELETE,
    Permission.WORKFLOW_DEPLOY,
    Permission.PIPELINE_CREATE,
    Permission.PIPELINE_UPDATE,
    Permission.ACTION_VALIDATE,
    Permission.SETTING_UPDATE,
    Permission.SYSTEM_REINDEX,
    Permission.JOB_READ_ALL,
    Permission.JOB_UPDATE,
}

# Machine writeback only: pipeline results and Batch job-status updates. Notably
# NOT the MCP server, which carries the invoking user's own token and so needs no
# service identity. job:update is why this role exists separately from any human
# role -- it writes another user's job status, which cannot be expressed as
# "the owner may update it" because the Batch poller is not the owner.
_SERVICE_ACCOUNT = frozenset({
    Permission.PROJECT_READ,
    Permission.RUN_READ,
    Permission.RUN_UPDATE,
    Permission.SAMPLE_READ,
    Permission.SAMPLE_CREATE,
    Permission.QCRECORD_CREATE,
    Permission.FILE_CREATE,
    Permission.FILE_UPDATE,
    Permission.JOB_READ_ALL,
    Permission.JOB_UPDATE,
})

_AUDITOR = READ_PERMISSIONS | {
    Permission.FILE_DOWNLOAD,
    Permission.SEARCH_QUERY,
    Permission.ROLE_READ,
}

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
}


ROLE_DEFINITIONS: dict[str, RoleDefinition] = {
    "member": RoleDefinition(
        RoleScope.GLOBAL, "Member",
        "Default for every authenticated user: reads catalogs, creates projects.",
        frozenset(_MEMBER),
    ),
    "lab_manager": RoleDefinition(
        RoleScope.GLOBAL, "Lab Manager",
        "Sequencing core: registers runs, demultiplexes, ingests vendor deliveries.",
        frozenset(_LAB_MANAGER),
    ),
    "platform_admin": RoleDefinition(
        RoleScope.GLOBAL, "Platform Administrator",
        "Owns the executable catalog and platform configuration.",
        frozenset(_PLATFORM_ADMIN),
    ),
    "service_account": RoleDefinition(
        RoleScope.GLOBAL, "Service Account",
        "Machine writeback for pipeline results and Batch job status. Not for humans.",
        frozenset(_SERVICE_ACCOUNT),
    ),
    "auditor": RoleDefinition(
        RoleScope.GLOBAL, "Auditor",
        "Read-only across the platform, for compliance, QA and read-only agents.",
        frozenset(_AUDITOR),
    ),
    "admin": RoleDefinition(
        RoleScope.GLOBAL, "Administrator",
        "Every permission. Recomputed on each sync, so new permissions are included.",
        ALL_PERMISSIONS,
    ),
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
