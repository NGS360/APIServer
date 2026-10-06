#!/usr/bin/env python3
"""
Grant or revoke `is_superuser` on an existing account.

Needed because BOOTSTRAP_ADMIN_USERNAMES only applies at account *creation*, and
nothing else can set the flag: the RBAC admin API is itself guarded by
CurrentSuperuser, so a database with no superuser cannot produce one through the
API. That is the chicken-and-egg this script exists to break.

Two situations call for it:

* A fresh tier, or a restored snapshot, where the accounts already exist and
  BOOTSTRAP_ADMIN_USERNAMES was not set before they were created.
* Offboarding -- taking the flag off someone who should no longer hold it. There
  is no other supported way to do that either.

Superuser short-circuits every permission check ahead of the resolver, so this is
the most consequential change any of these scripts can make. Hence: it prints the
current superuser roster before and after, it refuses to remove the last one
without --force, and it says who did it in the log.

Usage:
    PYTHONPATH=. python3 scripts/promote_superuser.py --username someone
    PYTHONPATH=. python3 scripts/promote_superuser.py --username someone --revoke
    PYTHONPATH=. python3 scripts/promote_superuser.py --list

Which database is written is decided by SQLALCHEMY_DATABASE_URI, so run it once
per tier. The tier and database are echoed back and must be confirmed at the
prompt; --yes skips that. --list and --dry-run never ask, because they write
nothing.

Prefer a role over this. `admin` holds every permission and is revocable through
the API; superuser is break-glass and bypasses the model entirely. If the answer
is "they need to administer things", grant the role -- see scripts/grant_role.py
in the deployment repository.
"""

import argparse
import getpass
import logging
import sys

from sqlmodel import Session, col, select

sys.path.insert(0, ".")

from api.auth.models import User  # noqa: E402
from core.config import get_settings  # noqa: E402
from core.db import engine  # noqa: E402

from scripts.create_service_account import _mask_uri, confirm_target  # noqa: E402

logger = logging.getLogger("promote_superuser")


def roster(session: Session) -> list[str]:
    return sorted(session.exec(
        select(User.username).where(col(User.is_superuser).is_(True))
    ).all())


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("--username", help="Account to change")
    ap.add_argument("--revoke", action="store_true",
                    help="Remove is_superuser instead of granting it")
    ap.add_argument("--list", action="store_true",
                    help="Print the current superuser roster and exit")
    ap.add_argument("--force", action="store_true",
                    help="Allow removing the last superuser")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--yes", "-y", action="store_true",
                    help="Skip the tier confirmation prompt")
    args = ap.parse_args()

    if not args.list and not args.username:
        ap.error("--username is required unless --list is given")

    settings = get_settings()
    print(f"tier:     {settings.ENVIRONMENT}")
    print(f"database: {_mask_uri(settings.SQLALCHEMY_DATABASE_URI)}")
    print()

    with Session(engine) as session:
        before = roster(session)
        print(f"superusers now ({len(before)}): {', '.join(before) or '(none)'}")

        if args.list:
            return 0

        user = session.exec(
            select(User).where(User.username == args.username)
        ).first()
        if user is None:
            raise SystemExit(
                f"error: no user {args.username!r} in this database. Check the "
                f"tier printed above -- accounts are per-tier, so one created "
                f"against a different tier does not exist here."
            )

        target = not args.revoke
        if user.is_superuser == target:
            print(f"\n{user.username} is already "
                  f"{'a superuser' if target else 'not a superuser'}; "
                  f"nothing to do")
            return 0

        # Removing the last superuser leaves nobody who can put it back through
        # the API -- only this script, which needs database access.
        if args.revoke and before == [user.username] and not args.force:
            raise SystemExit(
                f"error: {user.username} is the only superuser. Removing them "
                f"leaves no account that can grant it back through the API. "
                f"Pass --force if that is genuinely intended."
            )

        action = "grant is_superuser to" if target else "revoke is_superuser from"
        print()
        if args.dry_run:
            print(f"dry run: would {action} {user.username}")
            return 0

        confirm_target(settings, f"{action} {user.username}", args.yes)

        user.is_superuser = target
        session.add(user)
        session.commit()

        # Who did it. The audit-log table does not exist yet, so the application
        # log is the only record -- see docs/RBAC.md, Tier B.
        logger.warning(
            "is_superuser %s for %s by operator %s",
            "granted" if target else "revoked", user.username,
            getpass.getuser(),
        )

        after = roster(session)
        print(f"\nsuperusers now ({len(after)}): {', '.join(after) or '(none)'}")
        if not after:
            print("\nWARNING: this database now has no superuser. Nothing can "
                  "grant one through the API; this script is the only way back.")
    return 0


if __name__ == "__main__":
    logging.basicConfig(level=logging.WARNING, format="%(message)s")
    raise SystemExit(main())
