#!/usr/bin/env python3
"""
List roles, and what a role actually grants.

The companion to list_service_accounts.py. That script answers "what can this
account do"; the question behind it is "and what does that role grant", which
otherwise means reading api/rbac/roles.py, joining role and role_permission by
hand, and then still not knowing whether the tier in front of you agrees with the
code -- three separate steps, at exactly the moment somebody is waiting to be
told whether a grant is safe.

Usage:
    # Inventory: every role in this database
    PYTHONPATH=. python3 scripts/list_roles.py

    # One role in full: permissions, what they reach, who holds it
    PYTHONPATH=. python3 scripts/list_roles.py --role lab_manager

    # What granting an upgrade would actually add
    PYTHONPATH=. python3 scripts/list_roles.py --role member --diff lab_manager

    # For jq, for diffing tiers, or to attach to an access review. Application
    # logs go to stderr, so stdout is JSON and nothing else.
    PYTHONPATH=. python3 scripts/list_roles.py --json | jq '.roles[]
        | select(.warnings | length > 0) | {name, warnings}'

Four things are reported that a plain SELECT does not give you:

1. **Drift.** The database is what the resolver reads, api/rbac/roles.py is what
   the next startup will impose. For a builtin role those must agree; where they
   do not, one of them is about to change, and which way is worth knowing before
   somebody hand-edits role_permission again.
2. **What the permissions reach.** A permission only grants something if a route
   checks it, so the endpoints are read off the live dependency graph -- the same
   tags tests/test_route_coverage.py asserts against. Permissions no route checks
   yet are called out as inert rather than quietly counted as capability.
3. **Who holds it**, with superusers marked, since their roles decide nothing.
4. **Risk**, from the catalog -- including which permissions are refused even
   under RBAC_MODE=dry_run, because those are the ones already denying traffic.

Nothing is written, so there is no confirmation prompt and no --dry-run. The tier
and database are still printed: roles, grants and enforcement mode are per-tier,
and a role that looks harmless in dev may hold more in prod.
"""

import argparse
import json
import sys
import uuid
from collections import defaultdict

from sqlmodel import Session, select

sys.path.insert(0, ".")

from api.auth.models import User  # noqa: E402
from api.project.models import Project  # noqa: E402
from api.rbac.mode import ALWAYS_ENFORCE, current_mode  # noqa: E402
from api.rbac.models import (  # noqa: E402
    ProjectMember,
    Role,
    RolePermission,
    UserRole,
)
from api.rbac.permissions import CATALOG, PROJECT_SCOPABLE, Permission  # noqa: E402
from api.rbac.roles import ROLE_DEFINITIONS, RoleScope  # noqa: E402
from core.config import Settings, get_settings  # noqa: E402
from core.db import engine  # noqa: E402

# The catalog and the always-enforced set, keyed by the string form stored in
# role_permission -- a role's permissions come back from the database as strings,
# and comparing those against enum members everywhere invites a silent miss.
SPECS = {str(p): spec for p, spec in CATALOG.items()}
ENFORCED_IN_DRY_RUN = {str(p) for p in ALWAYS_ENFORCE}
SCOPABLE = {str(p) for p in PROJECT_SCOPABLE}

# Most severe first, so a role's headline risk is its first non-empty bucket.
RISK_ORDER = ("critical", "high", "medium", "low")

# How many holders the detail view prints before summarising the rest. `member`
# is granted to every account that has ever logged in, and a screen of usernames
# would bury the permissions above it.
HOLDER_LIMIT = 15


def _mask_uri(uri: str) -> str:
    import re
    return re.sub(r"://([^:@/]*):([^@]*)@", r"://\1:*****@", uri or "")


def count(n: int, noun: str) -> str:
    """"1 permission" / "3 permissions". Inlined often enough here to be worth it."""
    return f"{n} {noun}{'' if n == 1 else 's'}"


def verb(n: int) -> str:
    return "is" if n == 1 else "are"


def scope_of(role: Role) -> str:
    """The role's scope as a plain string, whichever form the driver returned."""
    return getattr(role.scope, "value", str(role.scope))


def risk_of(permission: str) -> str:
    """
    A permission's risk, or "unknown" for a string that is not in the catalog.

    role_permission holds free text -- the column is validated on write by the
    API, but not by the database, so a row inserted by hand can name anything.
    Such a row is inert (no guard cites it), and saying "unknown" rather than
    guessing "low" is what makes it visible.
    """
    spec = SPECS.get(permission)
    return spec.risk if spec else "unknown"


def risk_counts(permissions: set[str]) -> dict[str, int]:
    counts: dict[str, int] = defaultdict(int)
    for permission in permissions:
        counts[risk_of(permission)] += 1
    return dict(counts)


def risk_summary(permissions: set[str]) -> str:
    counts = risk_counts(permissions)
    parts = [f"{counts[r]} {r}" for r in (*RISK_ORDER, "unknown") if counts.get(r)]
    return ", ".join(parts) or "none"


# --- what the permissions reach -------------------------------------------

def route_guards() -> list[tuple[str, str, tuple[str, ...]]] | None:
    """
    Every guarded endpoint, as (endpoint, plane, required permissions).

    Read off the live dependency graph rather than from a hand-kept list: the
    guard factories in api/rbac/deps.py tag their closures with
    `rbac_permissions` precisely so this is possible, and
    tests/test_route_coverage.py already proves the tags are complete. A second,
    hand-maintained mapping would drift, and it would drift in the direction of
    over-reporting capability -- which is the wrong way round for a report
    somebody uses to decide whether a grant is safe.

    Returns None, rather than raising, if the application cannot be imported: the
    permissions themselves are the answer to the question asked, and losing the
    endpoint section is much better than losing the whole report because an
    unrelated import failed.
    """
    try:
        from core.middleware import _build_route_path_map
        from main import app
    except Exception as exc:  # pragma: no cover - environment-dependent
        print(f"note: could not import the application, so endpoints are not "
              f"shown ({type(exc).__name__}: {exc})", file=sys.stderr)
        return None

    # This FastAPI version does not flatten included routers, so the app holds
    # wrappers whose inner routes carry router-relative paths; the same map the
    # access log uses resolves them to full templates.
    mapping = _build_route_path_map(app)
    guards: list[tuple[str, str, tuple[str, ...]]] = []

    for route in app.routes:
        inner = [route]
        contexts = getattr(route, "effective_route_contexts", None)
        if callable(contexts):
            inner = [c.original_route for c in contexts()]
        for r in inner:
            if not hasattr(r, "dependant"):
                continue
            path = mapping.get(id(r), getattr(r, "path", ""))
            if not path.startswith("/api/v1"):
                continue

            found = []
            stack = list(r.dependant.dependencies)
            while stack:
                dependency = stack.pop()
                permissions = getattr(dependency.call, "rbac_permissions", None)
                if permissions:
                    found.append((
                        getattr(dependency.call, "rbac_plane", "global"),
                        tuple(str(p) for p in permissions),
                    ))
                stack.extend(dependency.dependencies)

            for method in sorted(r.methods - {"HEAD", "OPTIONS"}):
                for plane, permissions in found:
                    guards.append((f"{method} {path}", plane, permissions))

    return sorted(guards)


def split_reach(
    guards: list[tuple[str, str, tuple[str, ...]]],
    scope: str,
    permissions: set[str],
) -> tuple[list, list]:
    """
    Split the guarded endpoints into (reachable, partial) for one role.

    Two subtleties decide correctness here:

    * A project-scoped role is never consulted on the global plane, so a
      global-plane guard is unreachable with it no matter which permissions it
      carries. Counting those would credit a project role with the whole API.
    * A guard naming several permissions is reported as *partial* when the role
      holds some but not all of them. The tag records which permissions a guard
      cites, not how they are combined -- `require_permission(mode="any")` and
      the payload-dependent guard on PUT /jobs/{job_id} both accept one of the
      set, while the default requires all of them. Guessing either way would
      state something untrue, so a partial hit says so and names the permissions.
    """
    reachable, partial = [], []
    for endpoint, plane, required in guards:
        if scope == RoleScope.PROJECT.value and plane != "project":
            continue
        held = set(required) & permissions
        if not held:
            continue
        (reachable if held == set(required) else partial).append(
            (endpoint, plane, required)
        )
    return reachable, partial


# --- loading --------------------------------------------------------------

class Catalog:
    """
    Every role, its permissions and its holders, loaded in one pass.

    Grouped queries rather than per-role lookups, for the same reason
    list_service_accounts.py does it: the default view describes every role at
    once, and doing that N+1 times against a remote database is slow enough to
    stop people running it.
    """

    def __init__(self, session: Session):
        self.session = session
        self.roles: list[Role] = list(session.exec(
            select(Role).order_by(Role.scope, Role.name)
        ).all())

        self.permissions: dict[uuid.UUID, set[str]] = defaultdict(set)
        for role_id, permission in session.exec(
            select(RolePermission.role_id, RolePermission.permission)
        ).all():
            self.permissions[role_id].add(permission)

        # (username, is_superuser), so the detail view can mark the holders whose
        # role decides nothing.
        self.global_holders: dict[uuid.UUID, list[tuple[str, bool]]] = defaultdict(list)
        for username, is_superuser, role_id in session.exec(
            select(User.username, User.is_superuser, UserRole.role_id)
            .join(UserRole, UserRole.user_id == User.id)
            .order_by(User.username)
        ).all():
            self.global_holders[role_id].append((username, bool(is_superuser)))

        self.project_holders: dict[uuid.UUID, list[tuple[str, str]]] = defaultdict(list)
        for project_id, username, role_id in session.exec(
            select(Project.project_id, User.username, ProjectMember.role_id)
            .join(ProjectMember, ProjectMember.project_id == Project.id)
            .join(User, User.id == ProjectMember.user_id)
            .order_by(Project.project_id, User.username)
        ).all():
            self.project_holders[role_id].append((project_id, username))

    def by_name(self, name: str) -> Role | None:
        return next((r for r in self.roles if r.name == name), None)

    def grants(self, role: Role) -> int:
        """How many grants exist, in whichever plane this role is granted in."""
        if scope_of(role) == RoleScope.PROJECT.value:
            return len(self.project_holders[role.id])
        return len(self.global_holders[role.id])

    def drift(self, role: Role) -> tuple[set[str], set[str]]:
        """
        (in the database only, in the code only), for a builtin role.

        Empty for a custom role: nothing in code defines one, so there is nothing
        it can disagree with.
        """
        definition = ROLE_DEFINITIONS.get(role.name)
        if definition is None or not role.is_builtin:
            return set(), set()
        wanted = {str(p) for p in definition.permissions}
        held = self.permissions[role.id]
        return held - wanted, wanted - held


def warnings_for(catalog: Catalog, role: Role) -> list[str]:
    """
    Things about a role that someone reading this should act on.

    Only states that are wrong, or that mean the role grants more than it looks
    like it does. A warning list that includes the ordinary case teaches people
    to skim past it.
    """
    notes = []
    permissions = catalog.permissions[role.id]
    scope = scope_of(role)
    extra, missing = catalog.drift(role)

    if extra:
        notes.append(
            f"{count(len(extra), 'permission')} in the database that "
            f"api/rbac/roles.py does not give this builtin role "
            f"({', '.join(sorted(extra))}). "
            f"sync_rbac_catalog() removes them at the next startup, so this "
            f"grant is temporary -- and it is live until then."
        )
    if missing:
        notes.append(
            f"{count(len(missing), 'permission')} the code defines but the "
            f"database lacks ({', '.join(sorted(missing))}). This tier has not "
            f"restarted since they were added, so holders do not have them yet."
        )

    unknown = {p for p in permissions if p not in SPECS}
    if unknown:
        notes.append(
            f"{count(len(unknown), 'permission')} not in the catalog "
            f"({', '.join(sorted(unknown))}): no route can ever cite them, so "
            f"they grant nothing and never will. Almost certainly a typo in a "
            f"hand-written row."
        )

    if scope == RoleScope.PROJECT.value:
        global_only = {p for p in permissions if p in SPECS and p not in SCOPABLE}
        if global_only:
            notes.append(
                f"scope=project, but carries {len(global_only)} global-only "
                f"{'permission' if len(global_only) == 1 else 'permissions'} "
                f"({', '.join(sorted(global_only))}). The project "
                f"plane cannot grant those, so they are inert here."
            )

    if not permissions:
        notes.append("holds no permissions, so granting it changes nothing.")

    # Not said of a role that already holds the whole catalog -- `admin` is meant
    # to, and "this also carries everything" is not a finding there.
    if (str(Permission.ROLE_MANAGE) in permissions
            and not {str(p) for p in Permission} <= permissions):
        notes.append(
            f"grants {Permission.ROLE_MANAGE}: a holder can grant themselves any "
            f"role, so in practice this role carries every permission, not the "
            f"ones listed."
        )

    return notes


# --- output ---------------------------------------------------------------

def print_summary(catalog: Catalog, guards) -> None:
    if not catalog.roles:
        print("No roles in this database. The catalog is seeded at application "
              "startup -- start the API against this database first.")
        return

    rows = []
    for role in catalog.roles:
        permissions = catalog.permissions[role.id]
        reachable, _ = (split_reach(guards, scope_of(role), permissions)
                        if guards is not None else ([], []))
        rows.append((
            "!" if warnings_for(catalog, role) else " ",
            role.name,
            scope_of(role),
            "builtin" if role.is_builtin else "custom",
            str(len(permissions)),
            "-" if guards is None else str(len({e for e, _, _ in reachable})),
            str(catalog.grants(role)),
            risk_summary(permissions),
        ))

    headers = (" ", "ROLE", "SCOPE", "KIND", "PERMS", "ENDPOINTS", "GRANTS", "RISK")
    widths = [max(len(str(r[i])) for r in (*rows, headers))
              for i in range(len(headers))]
    line = "  ".join(f"{h:<{w}}" for h, w in zip(headers, widths)).rstrip()
    print(line)
    print("-" * len(line))
    for row in rows:
        print("  ".join(f"{c:<{w}}" for c, w in zip(row, widths)).rstrip())

    print()
    print(f"{len(catalog.roles)} roles. GRANTS counts holders for a global role "
          f"and memberships for a project one; ENDPOINTS counts the guarded "
          f"endpoints those permissions reach.")

    flagged = [r for r in catalog.roles if warnings_for(catalog, r)]
    if flagged:
        print(f"{len(flagged)} marked '!' have something worth looking at; "
              f"--role <name> explains what.")


def print_permissions(catalog: Catalog, role: Role) -> None:
    permissions = catalog.permissions[role.id]
    extra, _ = catalog.drift(role)

    print(f"permissions: {len(permissions)}  ({risk_summary(permissions)})")
    if not permissions:
        return

    by_resource: dict[str, list[str]] = defaultdict(list)
    for permission in sorted(permissions):
        spec = SPECS.get(permission)
        by_resource[spec.resource if spec else "?"].append(permission)

    for resource in sorted(by_resource):
        print(f"  {resource}")
        for permission in by_resource[resource]:
            spec = SPECS.get(permission)
            # '!' is the permission refused even under dry_run, '+' one the
            # database holds and the code does not -- the two facts that change
            # what a reader should do about the row.
            marks = ("!" if permission in ENFORCED_IN_DRY_RUN else " ") + \
                    ("+" if permission in extra else " ")
            print(f"    {marks} {permission:<26} {risk_of(permission):<8} "
                  f"{spec.description if spec else 'not in the catalog'}")

    if permissions & ENFORCED_IN_DRY_RUN:
        print()
        enforced = len(permissions & ENFORCED_IN_DRY_RUN)
        print(f"  ! {enforced} of these {verb(enforced)} refused even under "
              f"RBAC_MODE=dry_run (critical risk, or a delete), so "
              f"{'it is' if enforced == 1 else 'they are'} already denying "
              f"callers who lack them.")
    if extra:
        print(f"  + {len(extra)} of these {verb(len(extra))} in the database "
              f"only; the next startup removes "
              f"{'it' if len(extra) == 1 else 'them'}.")

    if scope_of(role) == RoleScope.GLOBAL.value:
        scopable = {p for p in permissions if p in SCOPABLE}
        if scopable:
            print()
            print(f"  {len(scopable)} of these are project-scopable. Held in a "
                  f"global role they apply to *every* project, not only the ones "
                  f"the holder is a member of.")


def print_endpoints(catalog: Catalog, role: Role, guards) -> None:
    if guards is None:
        print("endpoints: not resolved (the application could not be imported)")
        return

    permissions = catalog.permissions[role.id]
    reachable, partial = split_reach(guards, scope_of(role), permissions)
    total = len({e for e, _, _ in guards})

    print(f"endpoints: {len({e for e, _, _ in reachable})} of the {total} "
          f"guarded endpoints reachable with these permissions")
    for endpoint, plane, required in reachable:
        suffix = "  [project plane]" if plane == "project" else ""
        print(f"  {endpoint:<62} {', '.join(required)}{suffix}")

    if partial:
        print()
        print(f"  {len(partial)} more {verb(len(partial))} guarded by several "
              f"permissions of which this role holds only some. Whether that is "
              f"enough depends on the guard -- most require all of them, one "
              f"takes the requirement from the payload:")
        for endpoint, _, required in partial:
            held = sorted(set(required) & permissions)
            print(f"    {endpoint:<60} needs {', '.join(required)} "
                  f"(holds {', '.join(held)})")

    if scope_of(role) == RoleScope.PROJECT.value:
        print()
        print("  A project role is only consulted on the project plane, and only "
              "for the projects it is granted on. Global-plane endpoints are not "
              "reachable with it at all.")

    checked = {p for _, _, required in guards for p in required}
    inert = sorted(p for p in permissions if p in SPECS and p not in checked)
    if inert:
        print()
        print(f"  {len(inert)} of the permissions above {verb(len(inert))} not "
              f"checked by any route yet, so holding "
              f"{'it' if len(inert) == 1 else 'them'} changes nothing today -- "
              f"those endpoints are still anonymous (docs/RBAC.md, Phase 1):")
        for permission in inert:
            print(f"    {permission}")


def print_holders(catalog: Catalog, role: Role) -> None:
    if scope_of(role) == RoleScope.PROJECT.value:
        memberships = catalog.project_holders[role.id]
        if not memberships:
            print("granted to: nobody, on any project")
            return
        projects = {p for p, _ in memberships}
        print(f"granted to: {count(len(memberships), 'membership')} across "
              f"{count(len(projects), 'project')}")
        for project_id, username in memberships[:HOLDER_LIMIT]:
            print(f"  {project_id:<24} {username}")
        if len(memberships) > HOLDER_LIMIT:
            print(f"  ... and {len(memberships) - HOLDER_LIMIT} more (--json "
                  f"lists them all)")
        return

    holders = catalog.global_holders[role.id]
    if not holders:
        print("granted to: nobody")
        return

    superusers = [u for u, s in holders if s]
    print(f"granted to: {count(len(holders), 'account')}")
    for username, is_superuser in holders[:HOLDER_LIMIT]:
        print(f"  {username}{' *' if is_superuser else ''}")
    if len(holders) > HOLDER_LIMIT:
        print(f"  ... and {len(holders) - HOLDER_LIMIT} more (--json lists them "
              f"all)")
    if superusers:
        print(f"  * {len(superusers)} of these {verb(len(superusers))} "
              f"superusers: is_superuser "
              f"short-circuits every check ahead of any role, so what this role "
              f"grants them is irrelevant -- they hold everything.")


def print_detail(catalog: Catalog, role: Role, guards, show_endpoints: bool) -> None:
    print(f"role:        {role.name}")
    print(f"display:     {role.display_name}")
    print(f"description: {role.description or '-'}")
    print(f"scope:       {scope_of(role)}")
    if role.is_builtin:
        print("kind:        builtin  (permissions come from api/rbac/roles.py "
              "and are re-derived on every startup)")
    else:
        print("kind:        custom  (permissions are editable through "
              "PATCH /rbac/roles/{name})")
    print()
    print_permissions(catalog, role)
    print()
    if show_endpoints:
        print_endpoints(catalog, role, guards)
        print()
    print_holders(catalog, role)

    notes = warnings_for(catalog, role)
    if notes:
        print()
        for note in notes:
            print(f"warning: {note}")


def print_diff(catalog: Catalog, left: Role, right: Role) -> None:
    """
    What moving from one role to another changes.

    The question an actual grant request raises: somebody has `member` and wants
    `lab_manager`, and what matters is the delta, not either list. Both
    directions are shown because a "promotion" between two roles that are not
    nested also takes something away.
    """
    lhs = catalog.permissions[left.id]
    rhs = catalog.permissions[right.id]

    print(f"comparing:  {left.name} -> {right.name}")
    if scope_of(left) != scope_of(right):
        print(f"note:       different scopes ({scope_of(left)} vs "
              f"{scope_of(right)}), so these are granted in different planes "
              f"and one cannot replace the other.")
    print()

    for label, permissions in (("gained", rhs - lhs), ("lost", lhs - rhs)):
        print(f"{label}: {count(len(permissions), 'permission')}"
              f"{'  (' + risk_summary(permissions) + ')' if permissions else ''}")
        for permission in sorted(permissions):
            spec = SPECS.get(permission)
            mark = "!" if permission in ENFORCED_IN_DRY_RUN else " "
            print(f"  {mark} {permission:<26} {risk_of(permission):<8} "
                  f"{spec.description if spec else 'not in the catalog'}")
        print()

    print(f"unchanged: {count(len(lhs & rhs), 'permission')} held by both")


def as_json(catalog: Catalog, roles: list[Role], guards, settings: Settings,
            detail: bool) -> str:
    payload = {
        "tier": settings.ENVIRONMENT,
        "rbac_mode": str(current_mode()),
        "roles": [],
    }
    for role in roles:
        permissions = catalog.permissions[role.id]
        reachable, partial = (split_reach(guards, scope_of(role), permissions)
                              if guards is not None else ([], []))
        extra, missing = catalog.drift(role)
        entry = {
            "name": role.name,
            "display_name": role.display_name,
            "description": role.description,
            "scope": scope_of(role),
            "is_builtin": role.is_builtin,
            "permissions": sorted(permissions),
            "risk_counts": risk_counts(permissions),
            "grants": catalog.grants(role),
            "drift": {
                "database_only": sorted(extra),
                "code_only": sorted(missing),
            },
            "warnings": warnings_for(catalog, role),
        }
        # Absent rather than zero when the route guards could not be read: a 0
        # there would read as "this role reaches nothing".
        if guards is not None:
            entry["endpoints_reachable"] = len({e for e, _, _ in reachable})
        if detail:
            entry["permission_detail"] = [
                {
                    "permission": p,
                    "resource": SPECS[p].resource if p in SPECS else None,
                    "description": SPECS[p].description if p in SPECS else None,
                    "risk": risk_of(p),
                    "project_scopable": p in SCOPABLE,
                    "enforced_in_dry_run": p in ENFORCED_IN_DRY_RUN,
                    "in_catalog": p in SPECS,
                }
                for p in sorted(permissions)
            ]
            if guards is not None:
                entry["endpoints"] = {
                    "reachable": sorted({e for e, _, _ in reachable}),
                    "partial": [
                        {"endpoint": e, "requires": list(r)}
                        for e, _, r in partial
                    ],
                }
            if scope_of(role) == RoleScope.PROJECT.value:
                entry["granted_on"] = [
                    {"project_id": p, "username": u}
                    for p, u in catalog.project_holders[role.id]
                ]
            else:
                entry["holders"] = [
                    {"username": u, "is_superuser": s}
                    for u, s in catalog.global_holders[role.id]
                ]
        payload["roles"].append(entry)
    return json.dumps(payload, indent=2)


def resolve(catalog: Catalog, name: str) -> Role:
    role = catalog.by_name(name)
    if role is None:
        known = ", ".join(r.name for r in catalog.roles) or "none"
        raise SystemExit(
            f"error: no role {name!r} in this database. Check the tier above -- "
            f"custom roles are per-tier, and the builtin catalog only exists "
            f"once the API has started against this database.\n"
            f"known roles: {known}"
        )
    return role


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("--role", default=None,
                    help="Report one role in full: its permissions, what they "
                         "reach, and who holds it.")
    ap.add_argument("--diff", default=None, metavar="OTHER_ROLE",
                    help="Compare --role against this one, and report only what "
                         "differs. Answers what a grant would actually change.")
    ap.add_argument("--json", action="store_true",
                    help="Machine-readable output, for jq or for diffing two "
                         "tiers.")
    ap.add_argument("--no-routes", dest="routes", action="store_false",
                    help="Skip the endpoint section, which has to import the "
                         "application to read the route guards.")
    args = ap.parse_args()

    if args.diff and not args.role:
        ap.error("--diff compares against --role, so it needs one")
    if args.diff and args.json:
        ap.error("--diff is a report on two roles rather than a record of them; "
                 "for JSON, take both with --json and diff the permission lists")

    settings = get_settings()

    if not args.json:
        print(f"tier:     {settings.ENVIRONMENT}")
        print(f"database: {_mask_uri(settings.SQLALCHEMY_DATABASE_URI)}")
        # Permissions are only advisory until the mode says otherwise, so a
        # report of what a role grants is misread without it: under `off` or
        # `dry_run` the callers this role would refuse are still getting through.
        print(f"rbac:     {current_mode()}")
        print()

    # Only loaded when something will use it: it costs an application import,
    # and --diff is a question about permission sets alone.
    guards = route_guards() if args.routes and not args.diff else None

    with Session(engine) as session:
        catalog = Catalog(session)

        if args.diff:
            print_diff(catalog, resolve(catalog, args.role),
                       resolve(catalog, args.diff))
            return 0

        if args.role:
            roles, detail = [resolve(catalog, args.role)], True
        else:
            roles, detail = catalog.roles, False

        if args.json:
            print(as_json(catalog, roles, guards, settings, detail))
        elif detail:
            print_detail(catalog, roles[0], guards, args.routes)
        else:
            print_summary(catalog, guards)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
