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
    # user and its roles alone. Note the per-user active-key limit still applies.

The raw key is printed once and never recoverable -- only its hash is stored.
Capture it straight into the secret it belongs in. put-secret-value replaces the
whole SecretString, so read the current value, set just the one key with jq, and
write the merged result back -- otherwise every other key in the secret is lost:

    aws secretsmanager put-secret-value \\
        --secret-id <secret> \\
        --secret-string "$(aws secretsmanager get-secret-value \\
            --secret-id <secret> \\
            --query SecretString \\
            --output text | jq '.NGS360_API_TOKEN = "<key>"')"

The merge form needs an existing secret whose SecretString is already JSON. For a
brand-new secret there is nothing to merge into, so seed the full object once with
the literal JSON -- create-secret if the secret does not exist yet, otherwise a
plain put-secret-value -- and use the merge form for every write after that:

    aws secretsmanager create-secret \\
        --name <secret> \\
        --secret-string '{"NGS360_API_TOKEN":"<key>"}'

Rotation is two runs, in this order -- mint, deploy, then retire:

    # 1. mint the replacement
    PYTHONPATH=. python3 scripts/create_service_account.py --username svc-x
    # ... store it in the secret, redeploy the consumer, confirm it works ...

    # 2. retire everything else, sparing what you just deployed
    PYTHONPATH=. python3 scripts/create_service_account.py \\
        --username svc-x --revoke-key --except-key ngs360_AbCdE

Revoking is deliberately not folded into the minting run: it would take the old
key out before the new one is anywhere, so every rotation would carry an outage
window. --revoke-key therefore mints nothing and touches neither the user nor
its roles.

Revocation is the same soft-disable as POST /auth/api-keys/{id}/revoke -- the row
survives with revoked_at set, so an accidental revoke during a rotation can be
undone (UPDATE api_keys SET is_active = 1, revoked_at = NULL) as long as somebody
still holds the raw key.

Which database is written is decided by SQLALCHEMY_DATABASE_URI, so run it once
per tier. The tier and database are echoed back and have to be confirmed at the
prompt before anything is written -- --yes skips that, and --dry-run never asks
because it writes nothing.
"""

import argparse
import sys
from datetime import datetime, timedelta, timezone


from sqlmodel import Session, func, select

sys.path.insert(0, ".")

from api.auth.models import APIKey, APIKeyCreate, User  # noqa: E402
from api.auth.services import (  # noqa: E402
    create_user_api_key,
    ensure_timezone_aware,
    revoke_user_api_key,
)
from api.rbac.models import GrantSource, Role, UserRole  # noqa: E402
from core.config import Settings, get_settings  # noqa: E402
from core.db import engine  # noqa: E402
from core.security import hash_api_key  # noqa: E402


def _mask_uri(uri: str) -> str:
    import re
    return re.sub(r"://([^:@/]*):([^@]*)@", r"://\1:*****@", uri or "")


def confirm_target(settings: Settings, action: str, assume_yes: bool) -> None:
    """
    Make the operator name the tier before anything is written.

    Which database is written is decided entirely by SQLALCHEMY_DATABASE_URI --
    there is no --tier flag to get wrong, so the only thing between minting a
    prod key and minting a dev one is which environment the shell happened to
    have loaded. A y/N prompt gets answered reflexively; typing the tier back
    does not work unless the two lines above it were actually read.

    Note that ENVIRONMENT is only a label: core.config falls back to "dev" for
    any unrecognised value, so a run can print "dev" over a production URI. The
    database line is the authority, which is why both are printed and why the
    prompt tells the reader to check it.
    """
    if assume_yes:
        print(f"confirm:  --yes given, proceeding to {action}")
        print()
        return

    if not sys.stdin.isatty():
        raise SystemExit(
            "error: cannot confirm the tier -- stdin is not a terminal, and "
            "nothing has been written. Re-run interactively, or pass --yes if "
            "the tier and database above are certain to be the right ones."
        )

    prompt = (f"About to {action}.\n"
              f"Check the database above, then type the tier name "
              f"({settings.ENVIRONMENT}) to continue: ")
    try:
        answer = input(prompt).strip().lower()
    except (EOFError, KeyboardInterrupt):
        print()
        raise SystemExit("aborted, nothing written") from None

    if answer != settings.ENVIRONMENT:
        raise SystemExit(
            f"aborted, nothing written: expected {settings.ENVIRONMENT!r}, "
            f"got {answer!r}"
        )
    print()


def create_or_get_user(session: Session, username: str, email: str | None,
                       description: str | None) -> tuple[User, bool]:
    user = session.exec(select(User).where(User.username == username)).first()
    if user:
        return user, False

    # Refuse to reuse an address that already belongs to somebody.
    #
    # users.email is unique, so this would fail anyway -- but as a raw
    # IntegrityError that reads like a bug in the script rather than the thing
    # it actually is. And the constraint is not the real protection: if it were
    # ever relaxed, find_or_create_oauth_user matches on email ALONE, so a
    # service account holding a person's address would capture that person's
    # next SSO sign-in. They would either land on the service account -- with
    # its API-key-backed grants -- or be deduplicated to `username1` and lose
    # everything they had. Both are silent.
    if email:
        clash = session.exec(
            select(User).where(func.lower(User.email) == email.lower())
        ).first()
        if clash:
            raise SystemExit(
                f"error: {email} already belongs to user {clash.username!r}"
                f"{' (' + clash.full_name + ')' if clash.full_name else ''}.\n"
                f"\n"
                f"A service account must not share an address with a person. "
                f"find_or_create_oauth_user matches on email alone, so that "
                f"person's next SSO login would resolve to this service "
                f"account.\n"
                f"\n"
                f"Give the account its own address -- {username}@ngs360.invalid "
                f"is fine, it never needs to receive mail -- and record the "
                f"human owner in --description instead."
            )

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


def get_user(session: Session, username: str) -> User:
    """Look up an existing account. Unlike create_or_get_user, never creates one."""
    user = session.exec(select(User).where(User.username == username)).first()
    if user is None:
        raise SystemExit(
            f"error: no user {username!r} in this database. Check the tier "
            f"printed above -- accounts and keys are per-tier, so one minted "
            f"against a different tier does not exist here."
        )
    return user


def find_active_keys(session: Session, user: User) -> list[APIKey]:
    """
    Every key that can currently authenticate as this account.

    is_active is the only condition authenticate_api_key filters on, so this is
    exactly the set that revoking has to cover.
    """
    return list(session.exec(
        select(APIKey)
        .where(APIKey.user_id == user.id, APIKey.is_active.is_(True))
        .order_by(APIKey.created_at)
    ).all())


def matches_key(api_key: APIKey, token: str) -> bool:
    """
    Match an --except-key value against a key row.

    Accepts whichever form the operator has to hand: the id from
    GET /auth/api-keys, the 12-character prefix this script prints, or the raw
    key straight out of the secret -- the last by hash, since the raw key itself
    is never stored.
    """
    if token == str(api_key.id) or token == api_key.key_prefix:
        return True
    return token.startswith("ngs360_") and hash_api_key(token) == api_key.hashed_key


def split_keys(keys: list[APIKey],
               except_tokens: list[str]) -> tuple[list[APIKey], list[APIKey]]:
    """
    Split active keys into (to_revoke, to_keep).

    An --except-key matching nothing is fatal. The flag exists to protect the key
    you have just deployed, so a typo in it would revoke precisely the key you
    were trying to spare -- and silently, since revoking the rest would otherwise
    look like it worked.
    """
    keep_ids: set = set()
    for token in except_tokens:
        matched = [k for k in keys if matches_key(k, token)]
        if not matched:
            raise SystemExit(
                f"error: --except-key {token!r} matches no active key on this "
                f"account, so nothing has been revoked. Pass a key id, the "
                f"12-character prefix, or the raw key itself."
            )
        keep_ids.update(k.id for k in matched)

    return ([k for k in keys if k.id not in keep_ids],
            [k for k in keys if k.id in keep_ids])


def describe_key(api_key: APIKey) -> str:
    def stamp(value: datetime | None) -> str:
        if value is None:
            return "never"
        return value.isoformat(sep=" ", timespec="seconds")

    return (f"{api_key.key_prefix}...  created {stamp(api_key.created_at)}  "
            f"last used {stamp(api_key.last_used_at)}  {api_key.name}")


def recently_used(keys: list[APIKey], within: timedelta = timedelta(hours=24)
                  ) -> list[APIKey]:
    """Keys used recently enough that something is presumably still holding them."""
    cutoff = datetime.now(timezone.utc) - within
    return [k for k in keys
            if k.last_used_at is not None
            and ensure_timezone_aware(k.last_used_at) > cutoff]


def run_revoke(session: Session, username: str, except_tokens: list[str],
               dry_run: bool) -> int:
    user = get_user(session, username)
    print(f"user:     {user.username}")

    active = find_active_keys(session, user)
    if not active:
        print("keys:     none active, nothing to revoke")
        return 0

    to_revoke, kept = split_keys(active, except_tokens)
    for api_key in kept:
        print(f"kept:     {describe_key(api_key)}")

    if not to_revoke:
        print("keys:     every active key was excepted, nothing to revoke")
        return 0

    still_used = recently_used(to_revoke)
    if still_used:
        one = len(still_used) == 1
        print()
        print(f"warning: {len(still_used)} of the keys below "
              f"{'was' if one else 'were'} used in the last 24 hours, so "
              f"something is still presenting {'it' if one else 'them'}. If that "
              f"is not a consumer you have already moved onto a new key, "
              f"revoking will break it.")
        print()

    if dry_run:
        for api_key in to_revoke:
            print(f"revoke:   {describe_key(api_key)} (would revoke)")
        print()
        print(f"dry run: checks passed, nothing written "
              f"({len(to_revoke)} would be revoked)")
        return 0

    for api_key in to_revoke:
        # Same service POST /auth/api-keys/{id}/revoke uses, so this is the same
        # soft-disable and the row survives for the audit trail. It commits per
        # key, which is why each is reported as it goes: an interruption leaves
        # exactly the keys already printed revoked, and re-running finishes the
        # job.
        revoke_user_api_key(session, user, str(api_key.id))
        print(f"revoked:  {describe_key(api_key)}")

    print()
    print(f"{len(to_revoke)} key{'' if len(to_revoke) == 1 else 's'} revoked, "
          f"{len(kept)} still active.")
    if not kept:
        print("This account can no longer authenticate: no active key, and "
              "service accounts have no password.")
    return 0


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
    ap.add_argument("--revoke-key", "--revoke-keys", dest="revoke_keys",
                    action="store_true",
                    help="Revoke every active key for --username instead of "
                         "minting one. Pair with --except-key to spare the key "
                         "you have just deployed.")
    ap.add_argument("--except-key", dest="except_keys", action="append",
                    default=[], metavar="ID_PREFIX_OR_KEY",
                    help="Do not revoke this key: its id, its 12-character "
                         "prefix, or the raw key. Repeatable. Requires "
                         "--revoke-key.")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--yes", "-y", action="store_true",
                    help="Skip the tier confirmation prompt. For non-interactive "
                         "use only -- the tier and database are still printed.")
    args = ap.parse_args()

    # Reject the mint-flavoured arguments in revoke mode rather than accepting
    # and ignoring them: someone passing --role alongside --revoke-key has
    # misread what the run is going to do.
    if args.revoke_keys:
        mint_only = (
            ("--email", args.email),
            ("--description", args.description),
            ("--role", args.role),
            ("--key-name", args.key_name),
        )
        ignored = [name for name, value in mint_only if value]
        if ignored:
            ap.error(f"--revoke-key neither mints a key nor modifies the "
                     f"account, so {', '.join(ignored)} would do nothing")
    elif args.except_keys:
        ap.error("--except-key only means something together with --revoke-key")

    settings = get_settings()
    print(f"tier:     {settings.ENVIRONMENT}")
    print(f"database: {_mask_uri(settings.SQLALCHEMY_DATABASE_URI)}")
    print()

    # Confirm with the user this is the correct tier / database to use.
    #
    # A dry run is exempt: it writes nothing, and doing one first is precisely
    # how you check you are pointed where you think you are -- so making it the
    # cheap, unprompted option is the behaviour worth encouraging.
    if not args.dry_run:
        confirm_target(
            settings,
            (f"revoke API keys for {args.username!r}" if args.revoke_keys
             else f"mint an API key for {args.username!r}"),
            args.yes,
        )

    with Session(engine) as session:
        if args.revoke_keys:
            return run_revoke(session, args.username, args.except_keys,
                              args.dry_run)

        # --dry-run still runs every check, and rolls back instead of
        # committing. A dry run that skipped straight to "nothing written"
        # would report success for a command that cannot possibly work, which
        # is the opposite of what it is for.
        user, created = create_or_get_user(
            session, args.username, args.email, args.description
        )
        print(f"user:     {user.username} ({'created' if created else 'existing'})")

        if args.dry_run:
            if args.role:
                role = session.exec(
                    select(Role).where(Role.name == args.role)
                ).first()
                if role is None:
                    raise SystemExit(
                        f"error: role {args.role!r} does not exist in this "
                        f"database. The catalog is seeded at application "
                        f"startup -- start the API against it first."
                    )
                print(f"role:     {args.role} (exists, would be granted)")
            print("key:      would mint one")
            session.rollback()
            print()
            print("dry run: checks passed, nothing written")
            return 0

        if not user.is_verified or not user.is_active:
            # An existing account could predate this script.
            user.is_active = True
            user.is_verified = True
            session.add(user)
            print("          set is_active and is_verified (required for API keys)")

        if args.role:
            granted = grant_role(session, user, args.role)
            print(f"role:     {args.role} ({'granted' if granted else 'already held'})")

        # Counted before minting, so it is the number of keys this new one is
        # replacing rather than joining.
        other_active = len(find_active_keys(session, user))

        raw = mint_key(session, user, args.key_name or f"{args.username} key")
        session.commit()

    print()
    print("API key (shown once, not recoverable):")
    print(f"  {raw}")
    print()
    print("Store it now. put-secret-value replaces the whole SecretString, so")
    print("merge into the current value with jq rather than overwriting it:")
    print("  aws secretsmanager put-secret-value --secret-id <secret> \\")
    print("      --secret-string \"$(aws secretsmanager get-secret-value \\")
    print("          --secret-id <secret> --query SecretString --output text \\")
    print(f"          | jq '.NGS360_API_TOKEN = \"{raw}\"')\"")

    # Only worth saying when there is in fact something left to retire: on a
    # brand-new account this key is the only one, and pointing at --revoke-key
    # would just invite someone to revoke what they have only now minted.
    if other_active:
        print()
        print(f"This account has {other_active} other active "
              f"key{'' if other_active == 1 else 's'}. Once this one is deployed "
              f"and confirmed working, retire the rest:")
        print(f"  {sys.argv[0]} --username {args.username} \\")
        print(f"      --revoke-key --except-key {raw[:12]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
