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


# Graduated enforcement, withdrawn 2026-09-16.
#
# 25 permissions were enforced here on 09-15 on the evidence of zero would_deny
# across a 28-day window. Within a day two scientists received real 403s on
# `run:update` -- eleven refusals between them -- while writing samplesheets
# mid-run. Reverted to empty.
#
# The evidence was not wrong; it did not cover what it appeared to. run:update
# guards POST /runs/{run_id}/samplesheet, a route that was still *open and
# unguarded* for the whole window that was measured. An unguarded route runs no
# check, so it records no refusal, so "zero would_deny" said nothing about its
# callers. The same flaw applies to every permission graduated alongside a route
# closed in the same pass.
#
# That is why this is empty rather than trimmed: the defect is in the method, not
# in which permissions were chosen, and re-graduating anything needs a window
# measured *after* its routes were guarded. docs/RBAC.md carries the corrected
# procedure under *Graduating a permission to enforce*.
#
# The policy this serves: project data should be usable without a permission
# error. Enforcement is how that gets broken, so it stays off until the evidence
# genuinely covers the route -- while dry-run keeps recording what would have
# been refused, which is what made both of these findable.
_GRADUATED: frozenset[Permission] = frozenset()


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
