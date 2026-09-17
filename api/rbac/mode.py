"""
Enforcement mode.

Authorization ships dark and is turned up in stages: first `dry_run`, which
evaluates every check and logs what it *would* have refused without refusing
anything, then `enforce`. The dry-run window is the only chance to discover a
caller who depends on an endpoint nobody knew was reachable -- the alternative
is discovering it from a production outage.

`off` exists as an escape hatch for local work. It is deliberately not the
rollback plan: see docs/RBAC.md, where rollback is a forward fix (grant the
missing role) rather than disabling authorization estate-wide.
"""

from enum import StrEnum

from api.rbac.permissions import CATALOG, Permission
from core.config import get_settings


class RBACMode(StrEnum):
    """
    What a failed permission check does.

    OFF      -- do not check; every caller is allowed through.
    DRY_RUN  -- check, log the decision, allow regardless.
    ENFORCE  -- check, and raise 403 on failure.
    """

    OFF = "off"
    DRY_RUN = "dry_run"
    ENFORCE = "enforce"


# Permissions graduated to enforce on evidence, 2026-09-15.
#
# Each one guards at least one closed route and recorded *zero* would_deny
# across the 28-day gap-free window from 2026-08-18. That is the whole
# justification: not that the permission looks safe, but that no caller was
# refused it in production for four weeks.
#
# This is how Phase 5 happens -- permission by permission, each on its own
# evidence and revertible on its own -- rather than as one global flip. The mode
# stays `dry_run`, so every permission *not* in this set still logs instead of
# refusing.
#
# Deliberately a hand-maintained list rather than a rule. There is no property
# of a permission that makes it safe to enforce; only a measurement, which has a
# date and expires. Anything added here needs its own window, and the query is
# recorded in docs/RBAC.md under *Graduating a permission to enforce*.
#
# Not in this set, and why:
#   file:download, run:demux, project:submit_action, workflow:create,
#   workflow:deploy, run:associate, project:ingest, project:manage_members
#       -- have live would_deny in the window
#   manifest:read, manifest:validate
#       -- were clean until two callers surfaced *after* the routes closed on
#          09-11; grants applied 09-15, so they need a fresh window
_GRADUATED: frozenset[Permission] = frozenset({
    Permission.CHAT_USE,
    Permission.FILE_CREATE,
    Permission.FILE_READ,
    Permission.FILE_UPDATE,
    Permission.JOB_READ,
    Permission.JOB_UPDATE,
    Permission.MANIFEST_UPLOAD,
    Permission.PIPELINE_CREATE,
    Permission.PIPELINE_READ,
    Permission.PIPELINE_UPDATE,
    Permission.PROJECT_CREATE,
    Permission.PROJECT_READ,
    Permission.PROJECT_UPDATE,
    Permission.QCRECORD_CREATE,
    Permission.ROLE_READ,
    Permission.RUN_CREATE,
    Permission.RUN_UPDATE,
    Permission.SAMPLE_CREATE,
    Permission.SAMPLE_READ,
    Permission.SAMPLE_UPDATE,
    Permission.SEARCH_QUERY,
    Permission.SETTING_READ,
    Permission.USER_READ,
    Permission.WORKFLOW_READ,
    Permission.WORKFLOW_UPDATE,
})


def _always_enforce() -> frozenset[Permission]:
    """
    Permissions that are refused even in dry-run.

    Two sources, and the distinction matters:

    **Derived from the catalog**, so a permission added in a later release
    cannot quietly miss the net:

    - `critical` risk -- `setting:update` rewrites the bucket URIs and the
      manifest Lambda; `role:manage` is the grant plane itself.
    - every `:delete` -- the damage is not recoverable by re-granting a role.

    These have near-zero legitimate traffic, so allowing them through dry-run
    buys no discovery value while leaving the two ways to do real harm open for
    the length of the rollout.

    **Plus `_GRADUATED`**, which is the opposite kind of judgement: permissions
    enforced *because* they carry real traffic and none of it was ever refused.
    The first group is enforced despite no evidence; the second because of it.
    """
    return frozenset(
        permission
        for permission, spec in CATALOG.items()
        if spec.risk == "critical" or str(permission).endswith(":delete")
    ) | _GRADUATED


ALWAYS_ENFORCE: frozenset[Permission] = _always_enforce()


def current_mode() -> RBACMode:
    """
    The active mode, read per request.

    Not cached here: `get_settings()` is already `lru_cache`d, and reading
    through it means a test overriding settings takes effect without this
    module needing to know.
    """
    return RBACMode(get_settings().RBAC_MODE)


def effective_mode(permissions: tuple[Permission, ...]) -> RBACMode:
    """
    The mode that applies to this particular check.

    Escalates dry-run to enforce when any permission in the check is one of the
    always-enforced set. A route guarded by several permissions is escalated if
    *any* of them qualifies, because passing the check is what grants the whole
    route.
    """
    mode = current_mode()
    if mode is RBACMode.DRY_RUN and any(p in ALWAYS_ENFORCE for p in permissions):
        return RBACMode.ENFORCE
    return mode
