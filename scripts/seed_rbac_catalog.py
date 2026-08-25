#!/usr/bin/env python3
"""
Seed the builtin RBAC role catalog into a database, without starting the API.

Normally the catalog is reconciled at application startup (core/lifespan.py), a
deliberate choice recorded in docs/RBAC.md: the catalog is code derived from the
route table and changes in most feature PRs, so keeping it in migrations would
guarantee drift.

The gap that leaves: **the migration chain is not self-sufficient.** Two data
migrations depend on the catalog already existing --

    b7c4e19f2a83  Add RBAC tables             <- creates role, role_permission
    c3a81d47e56f  Backfill project ownership   <- needs role 'project_owner'
    e5f92c1b7d34  Backfill default user roles  <- needs role 'member'

-- so `alembic upgrade head` against an empty database fails partway with

    RuntimeError: role 'project_owner' is missing. The catalog is seeded at
    application startup -- start the API against this database before migrating.

In the three deployed tiers that resolved itself, because the app had been
running against those databases long before the backfills landed. It does not
resolve itself for a database created from scratch: a new tier, a restored
snapshot, or CI. Starting the whole API just to populate two tables is a poor
answer for those, hence this.

Usage:
    # The ordering that actually works on an empty database
    PYTHONPATH=. python3 -m alembic upgrade b7c4e19f2a83
    PYTHONPATH=. python3 scripts/seed_rbac_catalog.py --yes
    PYTHONPATH=. python3 -m alembic upgrade head

    # Reconcile an existing catalog after roles.py changes (what startup does)
    PYTHONPATH=. python3 scripts/seed_rbac_catalog.py

Which database is written is decided by SQLALCHEMY_DATABASE_URI, so run it once
per tier. The tier and database are echoed back and must be confirmed at the
prompt before anything is written; --yes skips that.

There is deliberately no --dry-run. sync_rbac_catalog commits internally, so a
dry run could only be faked by wrapping it in an outer transaction and rolling
back -- which does not work under pysqlite's savepoint handling, and would be a
lie the one time it silently failed on a real database. Answering "what does this
tier have, and does it match the code" is already `scripts/list_roles.py`, and
seeding is idempotent, so running it is itself the safe operation.
"""

import argparse
import sys

from sqlmodel import Session

sys.path.insert(0, ".")

from api.rbac.seed import sync_rbac_catalog  # noqa: E402
from core.config import get_settings  # noqa: E402
from core.db import engine  # noqa: E402

# Reuse the tier guard rather than reimplementing it -- one prompt, one set of
# semantics, and it already handles the non-interactive case.
from scripts.create_service_account import _mask_uri, confirm_target  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("--yes", "-y", action="store_true",
                    help="Skip the tier confirmation prompt. For non-interactive "
                         "use only -- the tier and database are still printed.")
    args = ap.parse_args()

    settings = get_settings()
    print(f"tier:     {settings.ENVIRONMENT}")
    print(f"database: {_mask_uri(settings.SQLALCHEMY_DATABASE_URI)}")
    print()

    confirm_target(settings, "seed the RBAC role catalog", args.yes)

    with Session(engine) as session:
        summary = sync_rbac_catalog(session)

    for key, value in sorted(summary.items()):
        print(f"  {key}: {value}")
    if sum(summary.values()) == 0:
        print("\ncatalog already matches api/rbac/roles.py, nothing to do")
    else:
        print("\ncatalog seeded")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
