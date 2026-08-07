"""
Seed the builtin roles and their permissions.

Runs at startup rather than in a data migration. The catalog is code derived from
the route table and changes on most feature pull requests; putting it in
migrations would mean a new revision per permission, which guarantees drift
within a couple of sprints. Rollback is also automatic -- deploying old code
restores the old catalog.

Three properties this has to get right:

1. **Concurrency.** All four Gunicorn workers run the lifespan, and a rolling
   deploy can have two instances starting at once. Seeding is wrapped in a MySQL
   advisory lock so only one writer runs at a time.
2. **Never delete.** Only builtin roles are touched, and only their permission
   rows are reconciled. Admin-created roles and *all* grants are left alone --
   deleting a role would cascade its user_role rows away, silently revoking
   access.
3. **Fail loudly when enforcing.** An empty catalog plus enforcement is a
   site-wide 403. Callers can assert the catalog is populated and refuse to start
   rather than serve an outage.
"""

from datetime import datetime, timezone

from sqlalchemy import text
from sqlmodel import Session, select

from api.rbac.models import Role, RolePermission
from api.rbac.roles import ROLE_DEFINITIONS
from core.logger import logger

# Name of the MySQL advisory lock guarding the seed. Arbitrary but must be stable.
_SEED_LOCK = "ngs360_rbac_seed"
_SEED_LOCK_TIMEOUT_SECONDS = 10


class _AdvisoryLock:
    """
    Best-effort cross-process lock, via MySQL GET_LOCK.

    A no-op on backends without it (SQLite in tests), where there is no
    concurrency to guard against anyway. Failing to acquire is not fatal: it means
    another process is seeding the same content, so this one can skip.
    """

    def __init__(self, session: Session, name: str, timeout: int):
        self.session = session
        self.name = name
        self.timeout = timeout
        self.acquired = False
        self.supported = session.get_bind().dialect.name == "mysql"

    def __enter__(self) -> bool:
        if not self.supported:
            self.acquired = True
            return True
        got = self.session.exec(
            text("SELECT GET_LOCK(:name, :timeout)").bindparams(
                name=self.name, timeout=self.timeout
            )
        ).one()[0]
        self.acquired = bool(got)
        if not self.acquired:
            logger.info(
                "RBAC seed lock held elsewhere; another process is seeding. Skipping."
            )
        return self.acquired

    def __exit__(self, *exc) -> None:
        if self.supported and self.acquired:
            self.session.exec(
                text("SELECT RELEASE_LOCK(:name)").bindparams(name=self.name)
            )


def sync_rbac_catalog(session: Session) -> dict[str, int]:
    """
    Reconcile the builtin roles in the database with api/rbac/roles.py.

    Returns a summary of what changed, for logging and tests.
    """
    summary = {"roles_created": 0, "roles_updated": 0,
               "permissions_added": 0, "permissions_removed": 0}

    with _AdvisoryLock(session, _SEED_LOCK, _SEED_LOCK_TIMEOUT_SECONDS) as acquired:
        if not acquired:
            return summary

        for name, definition in ROLE_DEFINITIONS.items():
            role = session.exec(select(Role).where(Role.name == name)).first()

            if role is None:
                role = Role(
                    name=name,
                    display_name=definition.display_name,
                    description=definition.description,
                    scope=definition.scope,
                    is_builtin=True,
                )
                session.add(role)
                session.flush()  # need role.id for the permission rows
                summary["roles_created"] += 1
            else:
                # Keep the metadata in step with code, but never flip is_builtin
                # off a role someone converted, and never touch scope on a role
                # that already has grants -- changing scope would make existing
                # grants meaningless.
                changed = False
                if role.display_name != definition.display_name:
                    role.display_name = definition.display_name
                    changed = True
                if role.description != definition.description:
                    role.description = definition.description
                    changed = True
                if not role.is_builtin:
                    role.is_builtin = True
                    changed = True
                if changed:
                    role.updated_at = datetime.now(timezone.utc)
                    session.add(role)
                    summary["roles_updated"] += 1

            # Reconcile the permission set. Builtin roles are code-defined, so
            # rows are added and removed to match -- this is the one place
            # deletion is correct, and it only ever touches role_permission,
            # never a grant.
            existing = {
                rp.permission: rp
                for rp in session.exec(
                    select(RolePermission).where(RolePermission.role_id == role.id)
                ).all()
            }
            wanted = {str(p) for p in definition.permissions}

            for permission in wanted - set(existing):
                session.add(RolePermission(role_id=role.id, permission=permission))
                summary["permissions_added"] += 1

            for permission in set(existing) - wanted:
                session.delete(existing[permission])
                summary["permissions_removed"] += 1

        session.commit()

    if any(summary.values()):
        logger.info(
            "RBAC catalog synced: %d role(s) created, %d updated, "
            "%d permission(s) added, %d removed",
            summary["roles_created"], summary["roles_updated"],
            summary["permissions_added"], summary["permissions_removed"],
        )
    else:
        logger.info("RBAC catalog already in sync (%d builtin roles)",
                    len(ROLE_DEFINITIONS))
    return summary


def assert_catalog_populated(session: Session) -> None:
    """
    Raise if no roles exist.

    Called at startup when authorization is being enforced. An empty catalog with
    enforcement on means every request is denied, so refusing to start -- and
    letting the load balancer pull the instance -- is much better than serving a
    site-wide outage as 403s.
    """
    count = len(session.exec(select(Role)).all())
    if count == 0:
        raise RuntimeError(
            "RBAC catalog is empty. Refusing to start with authorization enforced: "
            "every request would be denied. Check that sync_rbac_catalog() ran."
        )
