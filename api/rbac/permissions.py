"""
The permission catalog.

Permissions are a closed enum in code rather than rows in a table. A permission
only grants anything if some route checks it, so a database table could describe
intent but never capability -- an administrator inventing "project:archive" there
would get a permission that silently does nothing. As an enum member, a typo
fails at import instead of becoming a permanent, invisible 403.

Roles are database rows, which is the editability that actually matters: admins
compose arbitrary roles from this catalog through the API.

There are no wildcards. `ALL_PERMISSIONS` is a convenience for defining roles,
never something evaluated at check time -- a role holding "workflow:*" would
silently gain "workflow:purge" the day it was added, with nobody deciding to
grant it.

See docs/RBAC.md for the design rationale and the route mapping.
"""

from dataclasses import dataclass
from enum import StrEnum
from typing import Literal


class Permission(StrEnum):
    """Every permission the API recognises. 57 across 18 resources."""

    # --- Project-owned data ------------------------------------------------
    PROJECT_READ = "project:read"
    PROJECT_CREATE = "project:create"
    PROJECT_UPDATE = "project:update"
    PROJECT_DELETE = "project:delete"
    PROJECT_MANAGE_MEMBERS = "project:manage_members"
    PROJECT_SUBMIT_ACTION = "project:submit_action"
    PROJECT_INGEST = "project:ingest"

    SAMPLE_READ = "sample:read"
    SAMPLE_CREATE = "sample:create"
    SAMPLE_UPDATE = "sample:update"
    SAMPLE_DELETE = "sample:delete"

    QCRECORD_READ = "qcrecord:read"
    QCRECORD_CREATE = "qcrecord:create"
    QCRECORD_DELETE = "qcrecord:delete"

    FILE_READ = "file:read"
    FILE_DOWNLOAD = "file:download"
    FILE_CREATE = "file:create"
    FILE_UPDATE = "file:update"
    FILE_DELETE = "file:delete"
    FILE_BROWSE = "file:browse"

    # --- Platform resources -----------------------------------------------
    RUN_READ = "run:read"
    RUN_CREATE = "run:create"
    RUN_UPDATE = "run:update"
    RUN_ASSOCIATE = "run:associate"
    RUN_DEMUX = "run:demux"

    JOB_READ = "job:read"
    JOB_READ_ALL = "job:read_all"
    JOB_SUBMIT = "job:submit"
    JOB_UPDATE = "job:update"

    WORKFLOW_READ = "workflow:read"
    WORKFLOW_CREATE = "workflow:create"
    WORKFLOW_UPDATE = "workflow:update"
    WORKFLOW_DELETE = "workflow:delete"
    WORKFLOW_DEPLOY = "workflow:deploy"

    PIPELINE_READ = "pipeline:read"
    PIPELINE_CREATE = "pipeline:create"
    PIPELINE_UPDATE = "pipeline:update"

    PLATFORM_READ = "platform:read"
    PLATFORM_CREATE = "platform:create"

    VENDOR_READ = "vendor:read"
    VENDOR_CREATE = "vendor:create"
    VENDOR_UPDATE = "vendor:update"
    VENDOR_DELETE = "vendor:delete"

    SETTING_READ = "setting:read"
    SETTING_UPDATE = "setting:update"

    # --- Cross-cutting and infrastructure ---------------------------------
    MANIFEST_READ = "manifest:read"
    MANIFEST_UPLOAD = "manifest:upload"
    MANIFEST_VALIDATE = "manifest:validate"

    ACTION_READ = "action:read"
    ACTION_VALIDATE = "action:validate"

    SEARCH_QUERY = "search:query"
    CHAT_USE = "chat:use"

    USER_READ = "user:read"
    USER_MANAGE = "user:manage"

    ROLE_READ = "role:read"
    ROLE_MANAGE = "role:manage"

    SYSTEM_REINDEX = "system:reindex"


Risk = Literal["low", "medium", "high", "critical"]


@dataclass(frozen=True, slots=True)
class PermissionSpec:
    """Metadata for one permission, surfaced by GET /rbac/permissions."""

    resource: str
    description: str
    project_scopable: bool
    risk: Risk


# project_scopable=False means the permission may not appear in a role with
# scope=project. manifest:* and file:browse are global-only by necessity: they
# accept an arbitrary S3 URI, and no URI-to-project resolver exists.
CATALOG: dict[Permission, PermissionSpec] = {
    # --- Project-owned data ------------------------------------------------
    Permission.PROJECT_READ: PermissionSpec(
        "project", "View project metadata and attributes", True, "low"),
    Permission.PROJECT_CREATE: PermissionSpec(
        "project", "Create a new project", False, "low"),
    Permission.PROJECT_UPDATE: PermissionSpec(
        "project", "Change project metadata and attributes", True, "low"),
    Permission.PROJECT_DELETE: PermissionSpec(
        "project", "Delete a project (reserved; no route yet)", True, "high"),
    Permission.PROJECT_MANAGE_MEMBERS: PermissionSpec(
        "project", "Add, change and remove project members", True, "medium"),
    Permission.PROJECT_SUBMIT_ACTION: PermissionSpec(
        "project", "Submit a pipeline job for a project (spends compute)", True, "high"),
    Permission.PROJECT_INGEST: PermissionSpec(
        "project", "Ingest vendor data into a project (spends compute, writes S3)",
        True, "high"),

    Permission.SAMPLE_READ: PermissionSpec(
        "sample", "View and search samples", True, "low"),
    Permission.SAMPLE_CREATE: PermissionSpec(
        "sample", "Add samples to a project", True, "low"),
    Permission.SAMPLE_UPDATE: PermissionSpec(
        "sample", "Change sample metadata", True, "low"),
    Permission.SAMPLE_DELETE: PermissionSpec(
        "sample", "Delete a sample and its child rows", True, "medium"),

    Permission.QCRECORD_READ: PermissionSpec(
        "qcrecord", "View and search QC records", True, "low"),
    Permission.QCRECORD_CREATE: PermissionSpec(
        "qcrecord", "Create QC records", True, "low"),
    Permission.QCRECORD_DELETE: PermissionSpec(
        "qcrecord", "Delete a QC record", True, "medium"),

    Permission.FILE_READ: PermissionSpec(
        "file", "View file records and their versions", True, "low"),
    Permission.FILE_DOWNLOAD: PermissionSpec(
        "file", "Download file content", True, "medium"),
    Permission.FILE_CREATE: PermissionSpec(
        "file", "Register or upload files", True, "low"),
    Permission.FILE_UPDATE: PermissionSpec(
        "file", "Change file records", True, "low"),
    Permission.FILE_DELETE: PermissionSpec(
        "file", "Delete a file record", True, "high"),
    Permission.FILE_BROWSE: PermissionSpec(
        "file", "List an arbitrary S3 prefix; cannot be scoped to a project",
        False, "high"),

    # --- Platform resources -----------------------------------------------
    Permission.RUN_READ: PermissionSpec(
        "run", "View sequencing runs, samplesheets and metrics", False, "low"),
    Permission.RUN_CREATE: PermissionSpec(
        "run", "Register a sequencing run", False, "low"),
    Permission.RUN_UPDATE: PermissionSpec(
        "run", "Change a run or its samplesheet", False, "medium"),
    Permission.RUN_ASSOCIATE: PermissionSpec(
        "run", "Associate or dissociate samples and runs", False, "medium"),
    Permission.RUN_DEMUX: PermissionSpec(
        "run", "Submit a demultiplexing job (spends compute, deletes run QC records)",
        False, "high"),

    Permission.JOB_READ: PermissionSpec(
        "job", "View own jobs and their logs", False, "low"),
    Permission.JOB_READ_ALL: PermissionSpec(
        "job", "View all users' jobs, not only own", False, "medium"),
    Permission.JOB_SUBMIT: PermissionSpec(
        "job", "Submit a batch job (spends compute)", False, "high"),
    Permission.JOB_UPDATE: PermissionSpec(
        "job", "Write job status for any job; service accounts only", False, "medium"),

    Permission.WORKFLOW_READ: PermissionSpec(
        "workflow", "View workflows, versions, aliases and deployments", False, "low"),
    Permission.WORKFLOW_CREATE: PermissionSpec(
        "workflow", "Create workflows and versions", False, "medium"),
    Permission.WORKFLOW_UPDATE: PermissionSpec(
        "workflow", "Repoint a version alias; changes what executes", False, "high"),
    Permission.WORKFLOW_DELETE: PermissionSpec(
        "workflow", "Delete a version alias", False, "medium"),
    Permission.WORKFLOW_DEPLOY: PermissionSpec(
        "workflow", "Create and remove workflow deployments", False, "high"),

    Permission.PIPELINE_READ: PermissionSpec(
        "pipeline", "View pipelines", False, "low"),
    Permission.PIPELINE_CREATE: PermissionSpec(
        "pipeline", "Create a pipeline", False, "low"),
    Permission.PIPELINE_UPDATE: PermissionSpec(
        "pipeline", "Add or remove workflows in a pipeline", False, "medium"),

    Permission.PLATFORM_READ: PermissionSpec(
        "platform", "View sequencing platforms", False, "low"),
    Permission.PLATFORM_CREATE: PermissionSpec(
        "platform", "Create a sequencing platform", False, "medium"),

    Permission.VENDOR_READ: PermissionSpec(
        "vendor", "View vendors", False, "low"),
    Permission.VENDOR_CREATE: PermissionSpec(
        "vendor", "Create a vendor", False, "low"),
    Permission.VENDOR_UPDATE: PermissionSpec(
        "vendor", "Change a vendor", False, "low"),
    Permission.VENDOR_DELETE: PermissionSpec(
        "vendor", "Delete a vendor", False, "medium"),

    Permission.SETTING_READ: PermissionSpec(
        "setting", "View platform settings", False, "medium"),
    Permission.SETTING_UPDATE: PermissionSpec(
        "setting", "Change platform settings, including bucket URIs and Lambda ARNs",
        False, "critical"),

    # --- Cross-cutting and infrastructure ---------------------------------
    Permission.MANIFEST_READ: PermissionSpec(
        "manifest", "Read a manifest from an arbitrary S3 prefix", False, "medium"),
    Permission.MANIFEST_UPLOAD: PermissionSpec(
        "manifest", "Write a manifest to an arbitrary S3 prefix", False, "high"),
    Permission.MANIFEST_VALIDATE: PermissionSpec(
        "manifest", "Validate a manifest", False, "medium"),

    Permission.ACTION_READ: PermissionSpec(
        "action", "View action configurations and options", False, "low"),
    Permission.ACTION_VALIDATE: PermissionSpec(
        "action", "Validate an action configuration", False, "low"),

    Permission.SEARCH_QUERY: PermissionSpec(
        "search", "Run search queries", False, "low"),
    Permission.CHAT_USE: PermissionSpec(
        "chat", "Use the AI chat assistant", False, "medium"),

    Permission.USER_READ: PermissionSpec(
        "user", "Search the user directory", False, "low"),
    Permission.USER_MANAGE: PermissionSpec(
        "user", "Activate, verify and set superuser on users", False, "high"),

    Permission.ROLE_READ: PermissionSpec(
        "role", "View roles, permissions and grants", False, "low"),
    Permission.ROLE_MANAGE: PermissionSpec(
        "role", "Create and edit roles, grant and revoke them", False, "critical"),

    Permission.SYSTEM_REINDEX: PermissionSpec(
        "system", "Trigger an OpenSearch reindex", False, "high"),
}

ALL_PERMISSIONS: frozenset[Permission] = frozenset(Permission)

# Permissions a scope=project role may contain. Everything else is global-only.
PROJECT_SCOPABLE: frozenset[Permission] = frozenset(
    p for p, spec in CATALOG.items() if spec.project_scopable
)

# Every read-only permission, for composing observer-style roles.
READ_PERMISSIONS: frozenset[Permission] = frozenset(
    p for p in Permission if p.endswith((":read", ":read_all"))
)


def is_valid(value: str) -> bool:
    """Whether a string names a permission in this catalog."""
    return value in Permission._value2member_map_
