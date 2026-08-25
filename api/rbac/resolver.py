"""
The single place effective permissions are computed.

Effective access is a union of several inputs -- break-glass superuser, global
roles, and a project role -- and everything that needs to answer "can this user
do X" goes through this module: the route guards, GET /auth/me, and the admin
reporting endpoints. A second implementation in the reporting path would
eventually disagree with the enforcing one, and it would be the report that lies,
during an incident, which is the worst possible time.

Resolution is grant-only. There are no deny rules: a permission is either granted
by some plane or it is not. Suspension is handled upstream by is_active and
is_verified in get_current_active_user.

    1. user.is_superuser                                  -> allow (break-glass)
    2. permission in union(global roles)                  -> allow
    3. project given and permission in that project role  -> allow
    4. otherwise                                          -> deny

Nothing here enforces anything. Phase 4 wires these into routes behind a mode
flag; until then this only answers questions.
"""

import uuid
from dataclasses import dataclass, field

from sqlmodel import Session, select

from api.rbac.models import ProjectMember, Role, RolePermission, UserRole
from api.rbac.permissions import PROJECT_SCOPABLE, Permission


def global_permissions(session: Session, user_id: uuid.UUID) -> frozenset[str]:
    """Union of the permissions from every global role the user holds."""
    rows = session.exec(
        select(RolePermission.permission)
        .join(UserRole, UserRole.role_id == RolePermission.role_id)
        .where(UserRole.user_id == user_id)
    ).all()
    return frozenset(rows)


def project_permissions(
    session: Session, user_id: uuid.UUID, project_id: uuid.UUID
) -> frozenset[str]:
    """Permissions from the user's single role on this project, if any."""
    rows = session.exec(
        select(RolePermission.permission)
        .join(ProjectMember, ProjectMember.role_id == RolePermission.role_id)
        .where(
            ProjectMember.user_id == user_id,
            ProjectMember.project_id == project_id,
        )
    ).all()
    return frozenset(rows)


def global_role_names(session: Session, user_id: uuid.UUID) -> list[str]:
    """Names of the global roles the user holds, for display."""
    rows = session.exec(
        select(Role.name)
        .join(UserRole, UserRole.role_id == Role.id)
        .where(UserRole.user_id == user_id)
        .order_by(Role.name)
    ).all()
    return list(rows)


@dataclass
class AuthzContext:
    """
    One user's effective access, resolved once per request.

    Global permissions are loaded eagerly -- a single indexed query. Project
    permissions are loaded lazily and memoised per project, so a request touching
    one project costs one extra query and a request touching none costs zero.

    Deliberately not cached across requests: a process-level cache would make
    revocation lag by its TTL, and across several instances that lag is
    nondeterministic. Two indexed lookups per request is a price worth paying for
    grants that take effect immediately.
    """

    user_id: uuid.UUID
    username: str
    is_superuser: bool
    global_permissions: frozenset[str]
    session: Session
    _project_cache: dict[uuid.UUID, frozenset[str]] = field(default_factory=dict)

    @classmethod
    def for_user(cls, session: Session, user) -> "AuthzContext":
        return cls(
            user_id=user.id,
            username=user.username,
            is_superuser=bool(user.is_superuser),
            global_permissions=global_permissions(session, user.id),
            session=session,
        )

    # --- checks -----------------------------------------------------------

    def has(self, permission: Permission) -> bool:
        """Global-plane check. Superuser short-circuits ahead of any role."""
        return self.is_superuser or str(permission) in self.global_permissions

    def has_in_project(self, permission: Permission, project_id: uuid.UUID) -> bool:
        """
        Global grant OR project-role grant.

        A global role carrying a project-scopable permission applies to every
        project. That is forced by the data model: a flowcell spans projects,
        BatchJob has no project column, and the pipeline writeback account cannot
        be enrolled in every project whose results it writes.
        """
        if self.has(permission):
            return True
        return str(permission) in self.permissions_in_project(project_id)

    def permissions_in_project(self, project_id: uuid.UUID) -> frozenset[str]:
        cached = self._project_cache.get(project_id)
        if cached is None:
            cached = project_permissions(self.session, self.user_id, project_id)
            self._project_cache[project_id] = cached
        return cached

    # --- row filtering ----------------------------------------------------

    def visible_project_ids(
        self, permission: Permission = Permission.PROJECT_READ
    ) -> set[uuid.UUID] | None:
        """
        Projects where the user holds `permission`, or None for unrestricted.

        None means "add no WHERE clause" -- distinct from an empty set, which
        means "the user can see nothing". Callers must not conflate them: treating
        None as empty would hide everything from users who can see everything.
        """
        if self.has(permission):
            return None
        rows = self.session.exec(
            select(ProjectMember.project_id)
            .join(RolePermission, RolePermission.role_id == ProjectMember.role_id)
            .where(
                ProjectMember.user_id == self.user_id,
                RolePermission.permission == str(permission),
            )
        ).all()
        return set(rows)

    # --- reporting --------------------------------------------------------

    def effective_permissions(self) -> list[str]:
        """
        Every global permission, for display on /auth/me.

        Superusers hold everything by definition, so report that rather than an
        empty list, which would misleadingly suggest they had no access.
        """
        if self.is_superuser:
            return sorted(str(p) for p in Permission)
        return sorted(self.global_permissions)

    def effective_project_permissions(self, project_id: uuid.UUID) -> list[str]:
        """
        What this caller may do *in one project*, for the project response.

        The counterpart to effective_permissions, and it exists because the
        global list cannot answer the question: /rbac/me carries the global
        plane only, deliberately -- with a five-figure project count, inlining
        every project's grants would make that payload unbounded.

        Restricted to PROJECT_SCOPABLE because the rest are meaningless here: a
        project role can never carry them, so reporting them per project would
        invite a caller to read the absence of `setting:update` as something the
        project had to say about it.

        Goes through has_in_project rather than the membership rows, so a global
        grant is included. Reporting only the project-role grants would show an
        `admin` as holding nothing on the project, and hide every control from
        the account that can use all of them.
        """
        return sorted(
            str(p) for p in PROJECT_SCOPABLE if self.has_in_project(p, project_id)
        )
