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


def _always_enforce() -> frozenset[Permission]:
    """
    Permissions that are refused even in dry-run.

    Derived from the catalog rather than listed by hand, so a permission added
    in a later release cannot quietly miss the net:

    - `critical` risk -- `setting:update` rewrites the bucket URIs and the
      manifest Lambda; `role:manage` is the grant plane itself.
    - every `:delete` -- the damage is not recoverable by re-granting a role.

    These have near-zero legitimate traffic, so allowing them through dry-run
    buys no discovery value while leaving the two ways to do real harm open for
    the length of the rollout.
    """
    return frozenset(
        permission
        for permission, spec in CATALOG.items()
        if spec.risk == "critical" or str(permission).endswith(":delete")
    )


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
