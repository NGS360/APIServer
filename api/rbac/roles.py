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
    # Demultiplexing, open to every authenticated user as of 2026-09-28.
    #
    # This is a deliberate reversal, recorded because the reasoning that kept
    # run:demux out is still true and was not refuted: demux spends compute and
    # deletes the run's QC records, which is why it is the only high-risk run
    # permission. What changed is the judgement about who should be trusted with
    # it, not the assessment of what it does.
    #
    # The evidence behind the reversal: demux was already being done by eleven
    # people over a single week with no team in common, demux_operator had grown
    # to fourteen holders through purely reactive grants, and every one of those
    # grants was approved. A permission granted on request to everyone who asks
    # is not a restricted permission -- it is an unrestricted one with a ticket
    # queue in front of it. Consistent with the project stance that actions are
    # permissible except on restricted projects.
    #
    # run:update rides along because it is the other half of the same flow: the
    # samplesheet edit that precedes a demux submission. Granting demux without
    # it reproduces the 2026-09-11 incident, where ten of the eleven operators
    # could submit but not prepare.
    Permission.RUN_DEMUX,
    Permission.RUN_UPDATE,
    # Submitting a pipeline action, open to every authenticated user as of
    # 2026-10-07. Like run:demux this spends compute, and like run:demux the
    # grant follows a measurement rather than a principle.
    #
    # The measurement is the part worth keeping. Over 28 days every one of the
    # 44 refusals came from a caller with *no membership of the target project*,
    # and no project member was ever refused. So the project plane was not
    # mis-scoped, and widening project_viewer -- the obvious reading of "members
    # should be able to submit" -- would have fixed exactly nothing.
    #
    # Who was being refused also matters: not outsiders. The ten people involved
    # hold 182, 147, 90, 81, 58, 36, 24, 14, 11 and 0 project memberships
    # respectively. The user with 182 was refused on the two or three projects
    # they happen not to belong to. That is cross-project analysis work on an
    # open platform, not an access-control violation.
    #
    # A targeted role was the alternative and was worked up: it loses on the
    # holder list. The only existing role it fits is lab_manager, which carries
    # thirteen permissions beyond member including global file:download -- and
    # global file:download bypasses download_restricted on every project, so
    # granting it to ten analysts to fix one permission would quietly undo the
    # project download restrictions shipped in #425. A new narrow role avoids
    # that but needs ten grants plus a grant per new analyst, forever, for a
    # permission nobody has been refused *within* their own projects.
    #
    # The cost, stated because it is permanent and easy to miss: has_in_project
    # short-circuits on a global grant, so while this sits in `member` there is
    # no way to restrict submitting an action on a particular project. Weighed
    # against building an actions_restricted flag mirroring downloads, and that
    # lost on the evidence that download_restricted is set on 0 of 11,156
    # projects -- a second unused lever is not worth a column and a guard.
    Permission.PROJECT_SUBMIT_ACTION,
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
    # run:create removed 2026-09-28. Five people held it through lab_manager and
    # none of them had ever registered a run -- the only principal that has is
    # the NGS360-SequencersToS3 service account, which does it on a schedule.
    # Run registration is a machine job here, so it is now `run_registrar`.
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
    # run:create removed 2026-09-28 and moved to `run_registrar`. It was added
    # here on 2026-09-12 to complete the create/update pair, which was right at
    # the time -- but the pair is the wrong unit for runs specifically. Nine
    # accounts hold service_account for job and result writeback; exactly one of
    # them registers runs. Keeping run:create on the shared role meant eight
    # machine identities could create runs to fix one that needed to.
    Permission.RUN_UPDATE,
    Permission.SAMPLE_READ,
    Permission.SAMPLE_CREATE,
    Permission.SAMPLE_UPDATE,
    Permission.QCRECORD_CREATE,
    Permission.FILE_CREATE,
    Permission.FILE_UPDATE,
    Permission.JOB_READ_ALL,
    Permission.JOB_UPDATE,
    # Added 2026-09-28. A writeback identity that records pipeline results has
    # to resolve the workflow and version it is recording them for, and unlike
    # every human role it does not get workflow:read from `member` -- machine
    # accounts are created with `--role service_account` alone, which calls
    # grant_role directly and never goes through assign_default_roles.
    #
    # Worth stating because it is not a dry-run issue: workflow:read is in
    # _GRADUATED, so it is refused today rather than logged.
    Permission.WORKFLOW_READ,
})

_AUDITOR = READ_PERMISSIONS | {
    Permission.FILE_DOWNLOAD,
    Permission.SEARCH_QUERY,
    Permission.ROLE_READ,
}

# SUBSUMED as of 2026-09-28: `member` now carries run:demux and run:update, so
# this role grants nothing its holders do not already have. It is kept rather
# than deleted for two reasons -- sync_rbac_catalog only iterates
# ROLE_DEFINITIONS, so removing it here would orphan the row and its fourteen
# grants in every tier rather than clean them up; and if `member` is ever
# tightened again this is the role the grants should fall back to. The history
# below is left intact because it is the record of how the decision moved.
#
# Demultiplexing turned out to be done by eleven different people over one week,
# with different jobs and no single team among them. The obvious answer -- give
# them lab_manager -- was wrong: that role carries sixteen permissions beyond
# member, including *global* file:download, and has_in_project short-circuits on a
# global grant. Granting it would have exempted eleven people from the
# project-scoped downloads shipped days earlier, as a side effect of a decision
# about demux.
#
# So: exactly the permission that was refused, and nothing else. `member` already
# provides run:read, job:submit and job:read, which is the rest of the demux flow,
# so this role is one permission wide by design rather than by omission.
#
# It qualifies under the rule above -- run:demux is a write on a global resource --
# and it is the shape to copy the next time a single capability needs granting to
# people who share nothing else.
_DEMUX_OPERATOR = frozenset({
    Permission.RUN_DEMUX,
    # Added 2026-09-11. The role shipped with run:demux alone, described above as
    # "one permission wide by design rather than by omission". That was wrong, and
    # the correction is the more useful half of the lesson: minimal is only right
    # if you measured the whole flow.
    #
    # Closing POST /runs/{run_id}/samplesheet and PUT /runs/{run_id} surfaced it --
    # ten of the eleven demux operators had no run:update, so they would have
    # started receiving 403s on routes they use as part of the same job. run:update
    # is not project-scopable, so there was no per-project escape either.
    #
    # So the guard against over-granting cuts both ways, and the check that catches
    # both is the same one: resolve every observed caller on every route the
    # capability touches, not just the route that prompted the request.
    Permission.RUN_UPDATE,
})

# Run registration, which turned out to be one service's job rather than a
# capability several roles needed.
#
# Measured before narrowing rather than after: over 2026-08-18..09-28 exactly two
# principals called POST /runs. One is the NGS360-SequencersToS3 service account,
# which still does it daily. The other was a personal API key belonging to an
# administrator, named after the same job and revoked on 2026-09-18 -- a human
# doing by hand what the service account now does. No lab_manager holder has ever
# registered a run, and neither have the other eight service_account holders.
#
# So this is the same shape as _DEMUX_OPERATOR and _MANIFEST_OPERATOR, arrived at
# from the opposite direction: those roles were created because people were being
# refused something they needed, this one because accounts held something they
# did not use. Both corrections need the same measurement.
#
# Granted alongside service_account rather than replacing it -- run:read and the
# job writeback still come from there.
_RUN_REGISTRAR = frozenset({
    Permission.RUN_CREATE,
})

# Sample/run association, which is the run-metrics pipeline's job.
#
# Found the same way as _RUN_REGISTRAR, and the finding is the same shape twice
# over: on DELETE /runs/{run_id}/samples across 2026-09-01..29 there were exactly
# two callers. One is the NGS360-CollectRunMetrics-lambda service account, which
# clears a run's sample associations before repopulating them and was being
# recorded as would_deny on all 64 attempts. The other was a personal API key
# belonging to an administrator, revoked on 2026-09-04 -- again a human doing by
# hand what the pipeline now does.
#
# No lab_manager holder has ever called the route, although lab_manager carries
# run:associate. That grant is unused, and is left in place here rather than
# removed as a side effect of this fix.
#
# Granted alongside service_account: run:read, run:update and sample:create --
# the rest of the lambda's flow -- already come from there. This role adds the
# one permission that was refused.
_RUN_ASSOCIATOR = frozenset({
    Permission.RUN_ASSOCIATE,
})

# Manifest handling is global-only by necessity -- a manifest names an arbitrary
# S3 URI and no URI-to-project resolver covers it -- so it cannot be expressed as
# project membership and has to be a global role.
#
# Found the same way as demux_operator, by measuring who calls the routes: 15
# scientists plus one service account were using GET /manifest, POST /manifest and
# POST /manifest/validate, and `member` holds none of those permissions. Only
# lab_manager and admin did, and lab_manager carries sixteen permissions beyond
# member including run:create and project:ingest -- nothing a person uploading a
# manifest needs.
_MANIFEST_OPERATOR = frozenset({
    Permission.MANIFEST_READ,
    Permission.MANIFEST_UPLOAD,
    Permission.MANIFEST_VALIDATE,
})

# GA4GH workflow registration: register a workflow, add versions to it, and
# deploy a version to an execution backend. Done by one person today, whose only
# role is `member` -- so all 29 of her requests over 2026-08-19..28 were recorded
# as would_deny in the dry run and would 403 under enforce.
#
# The existing role carrying these is platform_admin, at 32 permissions including
# setting:update, system:reindex and vendor:delete. Granting it would have handed
# over thirty permissions with no demonstrated need in order to fix two. Same
# reasoning as _DEMUX_OPERATOR: grant the capability that was refused.
#
# workflow:read comes from `member`, so it is omitted rather than forgotten.
# workflow:delete is deliberately excluded -- publishing a workflow and destroying
# one are different privileges, and nobody has needed the latter. That is what
# workflow_admin is for.
_WORKFLOW_PUBLISHER = frozenset({
    Permission.WORKFLOW_CREATE,
    Permission.WORKFLOW_UPDATE,
    Permission.WORKFLOW_DEPLOY,
})

# Every workflow permission, including delete. Derived from the catalog rather
# than listed, so a new workflow:* permission joins it automatically -- for this
# role that is the intent, since "owns the workflow catalog outright" should not
# silently narrow when the catalog grows.
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
    "demux_operator": RoleDefinition(
        RoleScope.GLOBAL, "Demux Operator",
        "May run demultiplexing. Grants nothing else -- see the comment on "
        "_DEMUX_OPERATOR for why this is not lab_manager.",
        frozenset(_DEMUX_OPERATOR),
    ),
    "workflow_publisher": RoleDefinition(
        RoleScope.GLOBAL, "Workflow Publisher",
        "May register workflows, add versions, and deploy them. Cannot delete -- "
        "see the comment on _WORKFLOW_PUBLISHER for why this is not platform_admin.",
        frozenset(_WORKFLOW_PUBLISHER),
    ),
    "workflow_admin": RoleDefinition(
        RoleScope.GLOBAL, "Workflow Administrator",
        "Owns the workflow catalog outright, including deletion.",
        frozenset(_WORKFLOW_ADMIN),
    ),
    "run_registrar": RoleDefinition(
        RoleScope.GLOBAL, "Run Registrar",
        "May register sequencing runs. Grants nothing else -- see the comment on "
        "_RUN_REGISTRAR for why this is not service_account or lab_manager.",
        frozenset(_RUN_REGISTRAR),
    ),
    "run_associator": RoleDefinition(
        RoleScope.GLOBAL, "Run Associator",
        "May associate and dissociate samples and runs. Grants nothing else -- "
        "see the comment on _RUN_ASSOCIATOR for why this is not service_account.",
        frozenset(_RUN_ASSOCIATOR),
    ),
    "manifest_operator": RoleDefinition(
        RoleScope.GLOBAL, "Manifest Operator",
        "May read, upload and validate sample manifests. Grants nothing else -- "
        "see the comment on _MANIFEST_OPERATOR for why this is not lab_manager.",
        frozenset(_MANIFEST_OPERATOR),
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
