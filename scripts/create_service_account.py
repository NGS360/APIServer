#!/usr/bin/env python3
"""
Create a service-account user and mint an API key for it.

Needed because there is currently no supported way to create a machine identity:
`register_user` leaves is_verified=False, POST /auth/api-keys requires a verified
user via get_current_active_user, and no admin endpoint flips the flag. So a
service account presently requires direct database access -- which is what this
script provides, rather than leaving people to hand-write SQL against three
databases.

Usage:
    PYTHONPATH=. python3 scripts/create_service_account.py \\
        --username svc-batch-events \\
        --email ngs360-batch-events@bms.com \\
        --description "Writes Batch job status from the event Lambda" \\
        --role service_account

    # Re-running on an existing account mints an additional key and leaves the
    # user and its roles alone. Note the per-user active-key limit still applies,
    # so revoke the old key through the API when rotating.

The raw key is printed once and never recoverable -- only its hash is stored.
Capture it straight into the secret it belongs in, for example:

    aws secretsmanager put-secret-value \\
        --secret-id <secret> \\
        --secret-string "{\\"NGS360_API_TOKEN\\":\\"<key>\\"}"

Which database is written is decided by SQLALCHEMY_DATABASE_URI, so run it once
per tier. The tier is echoed back before anything is written.
"""

import argparse
import sys


from sqlmodel import Session, select

sys.path.insert(0, ".")

from api.auth.models import APIKeyCreate, User  # noqa: E402
from api.auth.services import create_user_api_key  # noqa: E402
from api.rbac.models import GrantSource, Role, UserRole  # noqa: E402
from core.config import get_settings  # noqa: E402
from core.db import engine  # noqa: E402


def _mask_uri(uri: str) -> str:
    import re
    return re.sub(r"://([^:@/]*):([^@]*)@", r"://\1:*****@", uri or "")


def create_or_get_user(session: Session, username: str, email: str | None,
                       description: str | None) -> tuple[User, bool]:
    user = session.exec(select(User).where(User.username == username)).first()
    if user:
        return user, False

    # is_verified=True is the whole point: without it every request using this
    # account's key fails on get_current_active_user with "Email not verified".
    # hashed_password stays None -- a service account must not be able to log in
    # interactively, only present its key.
    user = User(
        username=username,
        email=email,
        full_name=description or f"Service account: {username}",
        hashed_password=None,
        is_active=True,
        is_verified=True,
        is_superuser=False,
    )
    session.add(user)
    session.flush()
    return user, True


def grant_role(session: Session, user: User, role_name: str) -> bool:
    role = session.exec(select(Role).where(Role.name == role_name)).first()
    if role is None:
        raise SystemExit(
            f"error: role {role_name!r} does not exist. The catalog is seeded at "
            f"application startup -- start the API against this database first."
        )
    existing = session.exec(
        select(UserRole).where(UserRole.user_id == user.id, UserRole.role_id == role.id)
    ).first()
    if existing:
        return False
    session.add(UserRole(user_id=user.id, role_id=role.id,
                         source=GrantSource.MANUAL))
    return True


def mint_key(session: Session, user: User, name: str) -> str:
    """
    Delegates to the same service the API uses, so the key format, hashing and
    the per-user active-key limit all behave identically to a key created through
    POST /auth/api-keys.
    """
    _, raw = create_user_api_key(session, user, APIKeyCreate(name=name))
    return raw


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--username", required=True, help="e.g. svc-batch-events")
    ap.add_argument("--email", default=None)
    ap.add_argument("--description", default=None)
    ap.add_argument("--role", default=None,
                    help="Global role to grant, e.g. service_account or auditor")
    ap.add_argument("--key-name", default=None, help="Label for the API key")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    settings = get_settings()
    print(f"tier:     {settings.ENVIRONMENT}")
    print(f"database: {_mask_uri(settings.SQLALCHEMY_DATABASE_URI)}")
    print()

    if args.dry_run:
        print("dry run: nothing written")
        return 0

    with Session(engine) as session:
        user, created = create_or_get_user(
            session, args.username, args.email, args.description
        )
        print(f"user:     {user.username} ({'created' if created else 'existing'})")

        if not user.is_verified or not user.is_active:
            # An existing account could predate this script.
            user.is_active = True
            user.is_verified = True
            session.add(user)
            print("          set is_active and is_verified (required for API keys)")

        if args.role:
            granted = grant_role(session, user, args.role)
            print(f"role:     {args.role} ({'granted' if granted else 'already held'})")

        raw = mint_key(session, user, args.key_name or f"{args.username} key")
        session.commit()

    print()
    print("API key (shown once, not recoverable):")
    print(f"  {raw}")
    print()
    print("Store it now, e.g.:")
    print("  aws secretsmanager put-secret-value --secret-id <secret> \\")
    print(f'      --secret-string \'{{"NGS360_API_TOKEN":"{raw}"}}\'')
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
