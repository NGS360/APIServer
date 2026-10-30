#!/usr/bin/env python3
"""
List service accounts, and the roles and keys attached to an account.

The read-only counterpart to create_service_account.py. Answering "what machine
identities exist, what can they do, and is anything still using them" otherwise
means joining users, api_keys, user_role, role and project_member by hand -- and
those are exactly the questions asked during an access review, or at 2am when a
pipeline has started getting 403s.

Usage:
    # Inventory: every service account in this database
    PYTHONPATH=. python3 scripts/list_service_accounts.py

    # One account in full: flags, roles, permissions, keys
    PYTHONPATH=. python3 scripts/list_service_accounts.py --username svc-batch-events

    # Any account, human ones included -- --username already works on humans,
    # this is for the inventory
    PYTHONPATH=. python3 scripts/list_service_accounts.py --all

    # For jq, diffing tiers, or attaching to a review ticket. Application logs
    # go to stderr, so stdout is JSON and nothing else -- piping just works.
    PYTHONPATH=. python3 scripts/list_service_accounts.py --json | jq '.accounts[]
        | select(.warnings | length > 0) | {username, warnings}'

What counts as a service account, since nothing marks one: an account that
cannot log in interactively -- no password and no linked SSO provider, so an API
key is the only thing it can present -- or one holding the `service_account`
role. Either alone is enough. The first catches accounts created without --role,
the second catches a *human* account that has been granted the machine role,
which is worth seeing precisely because it is probably a mistake.

Nothing is written, so there is no confirmation prompt and no --dry-run. The
tier and database are still printed, because which database is read decides the
whole answer -- accounts, keys and grants are per-tier, and an account missing
here may simply live in another one.
"""

import argparse
import json
import sys
import uuid
from collections import defaultdict
from datetime import datetime, timedelta, timezone

from sqlmodel import Session, select

sys.path.insert(0, ".")

from api.auth.models import APIKey, OAuthProvider, User  # noqa: E402
from api.auth.services import ensure_timezone_aware  # noqa: E402
from api.project.models import Project  # noqa: E402
from api.rbac.mode import current_mode  # noqa: E402
from api.rbac.models import ProjectMember, Role, UserRole  # noqa: E402
from api.rbac.permissions import Permission  # noqa: E402
from api.rbac.resolver import global_permissions  # noqa: E402
from core.config import Settings, get_settings  # noqa: E402
from core.db import engine  # noqa: E402

SERVICE_ROLE_NAME = "service_account"


def _mask_uri(uri: str) -> str:
    import re
    return re.sub(r"://([^:@/]*):([^@]*)@", r"://\1:*****@", uri or "")


def stamp(value: datetime | None) -> str:
    """
    A timestamp for display, always marked UTC.

    Everything is stored in UTC, but SQLite hands back naive datetimes, so the
    same column prints with an offset against MySQL and without against SQLite.
    ensure_timezone_aware is what the request path already uses to paper over
    that; using it here too means "is this key stale" is not a question the
    reader has to answer by guessing which timezone they are looking at.
    """
    aware = ensure_timezone_aware(value)
    if aware is None:
        return "never"
    return aware.isoformat(sep=" ", timespec="seconds")


def iso(value: datetime | None) -> str | None:
    """Timestamp for --json: aware and unambiguous, or null."""
    aware = ensure_timezone_aware(value)
    return aware.isoformat() if aware else None


def key_state(api_key: APIKey, now: datetime) -> str:
    """
    Whether this key can authenticate right now.

    Three states, not two, because is_active alone does not decide it:
    authenticate_api_key filters the query on is_active and *then* rejects an
    expired key. So an active-but-expired key is dead while still looking alive
    in the api_keys table -- which is what makes it worth a state of its own
    here, since a consumer failing on one has nothing to do with a revocation.
    """
    if not api_key.is_active:
        return "revoked"
    expires_at = ensure_timezone_aware(api_key.expires_at)
    if expires_at is not None and expires_at < now:
        return "expired"
    return "usable"


def describe_key(api_key: APIKey, now: datetime) -> str:
    return (f"{api_key.key_prefix}...  {key_state(api_key, now):<7}  "
            f"created {stamp(api_key.created_at)}  "
            f"last used {stamp(api_key.last_used_at)}  {api_key.name}")


class Inventory:
    """
    Everything needed to describe accounts, loaded in one pass.

    Four grouped queries rather than per-user lookups: the point of the summary
    is to show every account at once, and doing that N+1 times against a remote
    database is slow enough to discourage running it. The whole users table is
    read, which is fine at this platform's scale (hundreds of rows) and would
    need revisiting only if that changed by orders of magnitude.
    """

    def __init__(self, session: Session):
        self.session = session
        self.users: list[User] = list(session.exec(
            select(User).order_by(User.username)
        ).all())
        self.by_id: dict[uuid.UUID, User] = {u.id: u for u in self.users}

        self.roles: dict[uuid.UUID, list[Role]] = defaultdict(list)
        for role, user_id in session.exec(
            select(Role, UserRole.user_id)
            .join(UserRole, UserRole.role_id == Role.id)
            .order_by(Role.name)
        ).all():
            self.roles[user_id].append(role)

        self.keys: dict[uuid.UUID, list[APIKey]] = defaultdict(list)
        for api_key in session.exec(
            select(APIKey).order_by(APIKey.created_at)
        ).all():
            self.keys[api_key.user_id].append(api_key)

        self.oauth_linked: set[uuid.UUID] = set(session.exec(
            select(OAuthProvider.user_id)
        ).all())

    def role_names(self, user: User) -> list[str]:
        return [r.name for r in self.roles[user.id]]

    def usable_keys(self, user: User, now: datetime) -> list[APIKey]:
        return [k for k in self.keys[user.id] if key_state(k, now) == "usable"]

    def stale_keys(self, user: User, now: datetime,
                   after: timedelta = timedelta(days=90)) -> list[APIKey]:
        """
        Usable keys that nothing appears to be presenting any more.

        A key never used falls back to its creation date rather than counting as
        infinitely stale: the key minted a minute ago has not been used yet
        either, and reporting that one as abandoned would put a "retire this"
        note on the output of every fresh create_service_account.py run.
        """
        cutoff = now - after
        stale = []
        for api_key in self.usable_keys(user, now):
            seen = ensure_timezone_aware(api_key.last_used_at or api_key.created_at)
            if seen is None or seen < cutoff:
                stale.append(api_key)
        return stale

    def login_method(self, user: User) -> str:
        """
        How this account can prove who it is, apart from an API key.

        A service account should be "key only": create_service_account.py leaves
        hashed_password None deliberately, so anything else on an account that
        looks like a machine identity means somebody has since given it a way to
        be logged into interactively.
        """
        methods = []
        if user.hashed_password:
            methods.append("password")
        if user.id in self.oauth_linked:
            methods.append("sso")
        return "+".join(methods) if methods else "key only"

    def is_service_account(self, user: User) -> bool:
        return (self.login_method(user) == "key only"
                or SERVICE_ROLE_NAME in self.role_names(user))

    def project_memberships(self, user: User) -> list[tuple[Project, Role, ProjectMember]]:
        """A user's project-scoped grants. Only needed for the detail view."""
        return list(self.session.exec(
            select(Project, Role, ProjectMember)
            .join(ProjectMember, ProjectMember.project_id == Project.id)
            .join(Role, Role.id == ProjectMember.role_id)
            .where(ProjectMember.user_id == user.id)
            .order_by(Project.project_id)
        ).all())

    def granted_by(self, user_id: uuid.UUID | None) -> str:
        """
        Resolve a granted_by id to a username.

        Falls back to the raw id rather than "unknown": a granter whose user row
        has since been deleted is still a real identity, and the id is what the
        audit trail can be followed with.
        """
        if user_id is None:
            return "-"
        granter = self.by_id.get(user_id)
        return granter.username if granter else str(user_id)


def warnings_for(inv: Inventory, user: User, now: datetime) -> list[str]:
    """
    Things about an account that someone reading this output should act on.

    Deliberately only states that are wrong or dangerous rather than merely
    notable -- a warning list that includes the ordinary case teaches people to
    skim past it.
    """
    notes = []
    role_names = inv.role_names(user)
    all_keys = inv.keys[user.id]
    usable = inv.usable_keys(user, now)

    if user.is_superuser:
        notes.append(
            "is_superuser: bypasses every permission check, so its roles are "
            "irrelevant -- it holds everything. Almost certainly not intended "
            "for a service account."
        )
    if not user.is_active or not user.is_verified:
        missing = " and ".join(
            f for f, ok in (("is_active", user.is_active),
                            ("is_verified", user.is_verified)) if not ok
        )
        notes.append(
            f"{missing} unset: every request from this account fails on "
            f"get_current_active_user, whatever keys it holds. "
            f"create_service_account.py --username {user.username} repairs this."
        )
    # Only a key-only account is broken by having no key. A person with SSO or a
    # password holding no API key is the ordinary case, and warning about it
    # under --all would mark most of the user table.
    if inv.login_method(user) == "key only":
        if not all_keys:
            notes.append("no API keys at all, and no password or SSO link "
                         "either: this account cannot authenticate.")
        elif not usable:
            notes.append(
                f"no usable key (all {len(all_keys)} revoked or expired), and no "
                f"password or SSO link: this account can no longer authenticate."
            )
    if usable and not role_names and not user.is_superuser:
        notes.append(
            "holds a usable key but no global role, so under RBAC_MODE=enforce "
            "it is refused everything a role would grant."
        )
    if (SERVICE_ROLE_NAME in role_names
            and inv.login_method(user) != "key only"):
        notes.append(
            f"holds {SERVICE_ROLE_NAME} but can also log in interactively "
            f"({inv.login_method(user)}): a person's account carrying machine "
            f"writeback permissions."
        )
    return notes


def print_summary(inv: Inventory, users: list[User], now: datetime,
                  scope: str) -> None:
    if not users:
        print(f"No {scope} in this database.")
        return

    rows = []
    for user in users:
        usable = inv.usable_keys(user, now)
        last_used = max(
            (ensure_timezone_aware(k.last_used_at) for k in inv.keys[user.id]
             if k.last_used_at is not None),
            default=None,
        )
        rows.append((
            "!" if warnings_for(inv, user, now) else " ",
            user.username,
            inv.login_method(user),
            ", ".join(inv.role_names(user)) or "-",
            f"{len(usable)}/{len(inv.keys[user.id])}",
            stamp(last_used),
        ))

    headers = (" ", "ACCOUNT", "AUTH", "GLOBAL ROLES", "KEYS", "LAST USED")
    widths = [max(len(str(r[i])) for r in (*rows, headers))
              for i in range(len(headers))]
    line = "  ".join(f"{h:<{w}}" for h, w in zip(headers, widths)).rstrip()
    print(line)
    print("-" * len(line))
    for row in rows:
        print("  ".join(f"{c:<{w}}" for c, w in zip(row, widths)).rstrip())

    print()
    print(f"{len(users)} {scope}. KEYS is usable/total -- a key is usable only "
          f"while it is neither revoked nor expired.")

    flagged = [u for u in users if warnings_for(inv, u, now)]
    if flagged:
        print(f"{len(flagged)} marked '!' have something worth looking at; "
              f"--username <account> explains what.")


def print_detail(inv: Inventory, user: User, now: datetime) -> None:
    print(f"account:  {user.username}")
    print(f"email:    {user.email or '-'}")
    print(f"name:     {user.full_name or '-'}")
    print(f"auth:     {inv.login_method(user)}")
    print(f"flags:    is_active={user.is_active} is_verified={user.is_verified} "
          f"is_superuser={user.is_superuser}")
    print(f"created:  {stamp(user.created_at)}")
    print(f"login:    {stamp(user.last_login)}   (last interactive login; keys "
          f"do not set it)")
    print()

    roles = inv.roles[user.id]
    if roles:
        print("global roles:")
        grants = {
            g.role_id: g for g in inv.session.exec(
                select(UserRole).where(UserRole.user_id == user.id)
            ).all()
        }
        for role in roles:
            grant = grants.get(role.id)
            source = grant.source.value if grant else "?"
            print(f"  {role.name:<20} {source:<10} "
                  f"granted {stamp(grant.granted_at) if grant else '?'} "
                  f"by {inv.granted_by(grant.granted_by if grant else None)}")
    else:
        print("global roles: none")
    print()

    memberships = inv.project_memberships(user)
    if memberships:
        print("project roles:")
        for project, role, member in memberships:
            label = project.project_id
            if project.name:
                label = f"{label} ({project.name})"
            print(f"  {label:<40} {role.name:<20} "
                  f"{member.source.value:<10} granted {stamp(member.granted_at)}")
    else:
        print("project roles: none")
    print()

    # Resolved through api.rbac.resolver rather than recomputed here. A second
    # implementation of "what can this account do" would eventually disagree
    # with the one the route guards use, and it would be this report that lied.
    # Not enumerated for a superuser: "all of them" is the whole finding, and 50
    # lines of catalog would bury the warning that says so.
    if user.is_superuser:
        print(f"permissions: all {len(Permission)} in the catalog -- "
              f"is_superuser short-circuits every check, ahead of any role")
    else:
        permissions = sorted(global_permissions(inv.session, user.id))
        print(f"permissions: {len(permissions)} in the global plane")
        for permission in permissions:
            print(f"  {permission}")
        if memberships:
            print("  (plus the project roles above, on those projects only)")
    print()

    keys = inv.keys[user.id]
    if keys:
        print("api keys:")
        for api_key in keys:
            print(f"  {describe_key(api_key, now)}")
        stale = inv.stale_keys(user, now)
        if stale:
            print()
            print(f"  {len(stale)} usable key{'' if len(stale) == 1 else 's'} "
                  f"unused for 90 days. Retire what nothing is presenting:")
            print(f"    scripts/create_service_account.py --username "
                  f"{user.username} \\")
            print("        --revoke-key --except-key <the one still in use>")
    else:
        print("api keys: none")

    notes = warnings_for(inv, user, now)
    if notes:
        print()
        for note in notes:
            print(f"warning: {note}")


def as_json(inv: Inventory, users: list[User], now: datetime,
            settings: Settings, detail: bool) -> str:
    payload = {
        "tier": settings.ENVIRONMENT,
        "rbac_mode": str(current_mode()),
        "generated_at": now.isoformat(),
        "accounts": [],
    }
    for user in users:
        entry = {
            "username": user.username,
            "email": user.email,
            "full_name": user.full_name,
            "login_method": inv.login_method(user),
            "is_active": user.is_active,
            "is_verified": user.is_verified,
            "is_superuser": user.is_superuser,
            "created_at": iso(user.created_at),
            "last_login": iso(user.last_login),
            "global_roles": inv.role_names(user),
            "api_keys": [
                {
                    "id": str(k.id),
                    "name": k.name,
                    "key_prefix": k.key_prefix,
                    "state": key_state(k, now),
                    "created_at": iso(k.created_at),
                    "last_used_at": iso(k.last_used_at),
                    "expires_at": iso(k.expires_at),
                }
                for k in inv.keys[user.id]
            ],
            "warnings": warnings_for(inv, user, now),
        }
        if detail:
            entry["project_roles"] = [
                {
                    "project_id": project.project_id,
                    "project_name": project.name,
                    "role": role.name,
                    "source": member.source.value,
                    "granted_at": iso(member.granted_at),
                }
                for project, role, member in inv.project_memberships(user)
            ]
            entry["permissions"] = (
                sorted(str(p) for p in Permission) if user.is_superuser
                else sorted(global_permissions(inv.session, user.id))
            )
        payload["accounts"].append(entry)
    return json.dumps(payload, indent=2)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--username", default=None,
                    help="Report one account in full. Works on any account, "
                         "human ones included.")
    ap.add_argument("--all", dest="all_users", action="store_true",
                    help="List every account, not only the ones that look like "
                         "service accounts.")
    ap.add_argument("--json", action="store_true",
                    help="Machine-readable output, for jq or for diffing two "
                         "tiers.")
    args = ap.parse_args()

    if args.username and args.all_users:
        ap.error("--all widens the listing, so it does nothing alongside "
                 "--username, which reports a single account")

    settings = get_settings()
    now = datetime.now(timezone.utc)

    if not args.json:
        print(f"tier:     {settings.ENVIRONMENT}")
        print(f"database: {_mask_uri(settings.SQLALCHEMY_DATABASE_URI)}")
        # Roles are only advisory until the mode says otherwise, so a report of
        # who holds what is misread without it: under `off` or `dry_run` an
        # account with no role is not in fact being refused anything yet.
        print(f"rbac:     {current_mode()}")
        print()

    with Session(engine) as session:
        inv = Inventory(session)

        if args.username:
            user = next((u for u in inv.users
                         if u.username == args.username), None)
            if user is None:
                raise SystemExit(
                    f"error: no account {args.username!r} in this database. "
                    f"Check the tier above -- accounts are per-tier, so one "
                    f"created against a different tier does not exist here."
                )
            users, scope, detail = [user], "account", True
        elif args.all_users:
            users, scope, detail = inv.users, "accounts", False
        else:
            users = [u for u in inv.users if inv.is_service_account(u)]
            scope, detail = "service accounts", False

        if args.json:
            print(as_json(inv, users, now, settings, detail))
        elif detail:
            print_detail(inv, users[0], now)
        else:
            print_summary(inv, users, now, scope)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
