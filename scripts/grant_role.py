#!/usr/bin/env python3
"""
Grant a global role or a project membership.

Grants are per-tier operational data, not schema: which people need which role
differs between dev, staging and prod, and the set changes continuously. So this
is a CLI rather than a migration -- a migration would replay the same grants
against every tier, including ones where those accounts do not exist.

It delegates to api/rbac/services.py, the same functions the admin API uses, so
scope validation and the last-owner and last-role-manager guards behave
identically here. A second implementation would eventually disagree with the one
the API enforces.

Usage:
    # One global role
    PYTHONPATH=. python3 scripts/grant_role.py --user asmith --role lab_manager

    # One project membership (--project takes the project business key)
    PYTHONPATH=. python3 scripts/grant_role.py \\
        --user asmith --role project_contributor --project P-YYYYMMDD-NNNN

    # A batch, which is the reviewable form for a planned rollout
    PYTHONPATH=. python3 scripts/grant_role.py --from-file grants.txt --dry-run

Batch file format -- whitespace or comma separated, '#' comments, blank lines
ignored. A third field means a project membership, two means a global role:

    # user      role                  project
    asmith      lab_manager
    bjones      project_contributor   P-YYYYMMDD-NNNN

Every run is idempotent: a grant the account already holds is reported and
skipped. --dry-run resolves and validates everything, then rolls back, so a
typo in a username or role is caught before anything is written.

Which database is written is decided by SQLALCHEMY_DATABASE_URI, so run it once
per tier. The tier is echoed before anything is written.

Revoking is deliberately not here: the admin API already does it
(DELETE /api/v1/rbac/users/{username}/roles/{role_name} and
DELETE /api/v1/projects/{project_id}/members/{username}), with the same guards.
"""

import argparse
import re
import sys

from fastapi import HTTPException
from sqlmodel import Session, select

sys.path.insert(0, ".")

from api.project.models import Project  # noqa: E402
from api.rbac import services  # noqa: E402
from api.rbac.roles import RoleScope  # noqa: E402
from core.config import get_settings  # noqa: E402
from core.db import engine  # noqa: E402


def _mask_uri(uri: str) -> str:
    return re.sub(r"://([^:@/]*):([^@]*)@", r"://\1:*****@", uri or "")


def parse_batch(path: str) -> list[tuple[str, str, str | None]]:
    """Read the batch file into (user, role, project|None) triples."""
    entries: list[tuple[str, str, str | None]] = []
    try:
        fh = open(path)
    except OSError as exc:
        raise SystemExit(f"error: cannot read {path}: {exc.strerror}")
    with fh:
        for lineno, raw in enumerate(fh, 1):
            line = raw.split("#", 1)[0].strip()
            if not line:
                continue
            fields = [f for f in re.split(r"[,\s]+", line) if f]
            if len(fields) == 2:
                entries.append((fields[0], fields[1], None))
            elif len(fields) == 3:
                entries.append((fields[0], fields[1], fields[2]))
            else:
                raise SystemExit(
                    f"{path}:{lineno}: expected 'user role' or "
                    f"'user role project', got {len(fields)} field(s): {line!r}"
                )
    if not entries:
        raise SystemExit(f"{path}: no grants found")
    return entries


def apply_grant(session: Session, username: str, role_name: str,
                project_key: str | None) -> str:
    """
    Apply one grant. Returns a human-readable outcome.

    Raises SystemExit with a usable message rather than letting the API's
    HTTPException surface as a traceback.
    """
    try:
        user = services.get_user_or_404(session, username)
        role = services.get_role_or_404(session, role_name)
    except HTTPException as exc:
        raise SystemExit(f"error: {exc.detail}")

    if project_key is None:
        if role.scope is not RoleScope.GLOBAL:
            raise SystemExit(
                f"error: {role_name!r} is a project role; pass --project, or "
                f"the grant would silently do nothing"
            )
        try:
            granted = services.grant_global_role(session, user, role,
                                                 granted_by=None)
        except HTTPException as exc:
            raise SystemExit(f"error: {exc.detail}")
        return (f"granted {role_name}" if granted
                else f"already held {role_name}")

    if role.scope is not RoleScope.PROJECT:
        raise SystemExit(
            f"error: {role_name!r} is a global role; drop --project. A global "
            f"role applies to every project, which is not what naming one means."
        )

    project = session.exec(
        select(Project).where(Project.project_id == project_key)
    ).first()
    if project is None:
        raise SystemExit(f"error: no project with id {project_key!r}")

    try:
        _, created = services.set_project_member(
            session, project.id, user, role, granted_by=None
        )
    except HTTPException as exc:
        raise SystemExit(f"error: {exc.detail}")
    return (f"added to {project_key} as {role_name}" if created
            else f"already a member of {project_key}, role set to {role_name}")


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("--user", help="Username to grant to")
    ap.add_argument("--role", help="Role name, e.g. lab_manager or project_owner")
    ap.add_argument("--project", default=None,
                    help="Project business key; makes this a project membership")
    ap.add_argument("--from-file", default=None,
                    help="Apply a batch of grants from a file")
    ap.add_argument("--dry-run", action="store_true",
                    help="Validate and report, then roll back")
    args = ap.parse_args()

    if args.from_file:
        if args.user or args.role or args.project:
            ap.error("--from-file cannot be combined with --user/--role/--project")
        entries = parse_batch(args.from_file)
    else:
        if not args.user or not args.role:
            ap.error("--user and --role are required unless --from-file is given")
        entries = [(args.user, args.role, args.project)]

    settings = get_settings()
    print(f"tier:     {settings.ENVIRONMENT}")
    print(f"database: {_mask_uri(settings.SQLALCHEMY_DATABASE_URI)}")
    print(f"grants:   {len(entries)}")
    if args.dry_run:
        print("mode:     dry run (nothing will be written)")
    print()

    changed = 0

    # The service functions commit internally, which a plain session.rollback()
    # cannot undo -- so a naive --dry-run would write. Binding the session to an
    # outer connection transaction with join_transaction_mode="create_savepoint"
    # turns each of those commits into a savepoint release, leaving the outer
    # transaction to decide. That is what makes the dry run exercise the real
    # code path, guards included, instead of a validation-only imitation of it.
    connection = engine.connect()
    outer = connection.begin()
    try:
        with Session(bind=connection,
                     join_transaction_mode="create_savepoint") as session:
            for username, role_name, project_key in entries:
                outcome = apply_grant(session, username, role_name, project_key)
                if outcome.startswith(("granted", "added")):
                    changed += 1
                print(f"  {username:14s} {outcome}")

        if args.dry_run:
            outer.rollback()
            print()
            print(f"dry run: checks passed, {changed} grant(s) would be applied")
            return 0

        outer.commit()
    except BaseException:
        # Nothing is half-applied: a bad entry in a batch aborts the whole run.
        if outer.is_active:
            outer.rollback()
        raise
    finally:
        connection.close()

    print()
    print(f"applied {changed} grant(s); {len(entries) - changed} already in place")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
