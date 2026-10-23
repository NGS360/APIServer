"""
Role and grant mutations.

Every write validates against the code-level catalog, because a role holding a
permission no route checks is not a capability -- it is a lie about one. The
guardrails here exist to stop the two mistakes that are hard to undo: revoking
your own ability to grant, and orphaning a project nobody can administer.
"""

import logging
import uuid
from datetime import datetime, timezone

from fastapi import HTTPException, status
from sqlmodel import Session, col, func, or_, select

from api.auth.models import User
from api.project.models import Project
from api.rbac.models import (
    GrantSource,
    ProjectMember,
    ProjectMembershipPublic,
    Role,
    RolePermission,
    UserAccessPublic,
    UserAdminPublic,
    UserRole,
    UsersAdminPublic,
)
from api.rbac.permissions import ALL_PERMISSIONS, PROJECT_SCOPABLE, Permission
from api.rbac.resolver import AuthzContext, global_role_names
from api.rbac.roles import RoleScope
from core.config import get_settings

logger = logging.getLogger(__name__)


def _conflict(detail: str) -> HTTPException:
    return HTTPException(status.HTTP_409_CONFLICT, detail=detail)


def _bad_request(detail: str) -> HTTPException:
    return HTTPException(status.HTTP_400_BAD_REQUEST, detail=detail)


def _not_found(detail: str) -> HTTPException:
    return HTTPException(status.HTTP_404_NOT_FOUND, detail=detail)


def validate_permissions(permissions: list[str], scope: RoleScope) -> set[str]:
    """
    Reject anything not in the catalog, and global-only permissions on a project
    role -- the project plane can never honour those, so accepting one would
    create a permission that silently does nothing.
    """
    known = {str(p) for p in ALL_PERMISSIONS}
    unknown = sorted(set(permissions) - known)
    if unknown:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"Unknown permissions: {', '.join(unknown)}",
        )
    if scope is RoleScope.PROJECT:
        scopable = {str(p) for p in PROJECT_SCOPABLE}
        not_scopable = sorted(set(permissions) - scopable)
        if not_scopable:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=(
                    "These permissions cannot be granted by a project role: "
                    f"{', '.join(not_scopable)}"
                ),
            )
    return set(permissions)


def assign_default_roles(session: Session, user: User) -> list[str]:
    """
    Grant a newly created user their starting roles. Returns what was granted.

    Called from both user-creation paths. Deliberately best-effort: it logs and
    returns empty rather than raising if the role is missing. A user who ends up
    with no role gets 403s, which is visible and fixable by an administrator; an
    exception here would instead fail the registration or the SSO callback
    outright, locking people out of the product because of an authorization
    misconfiguration. The wrong failure to choose is the one that denies login.

    Superusers additionally receive `admin`. That is inert today -- is_superuser
    already short-circuits ahead of every role -- and exists so that dropping
    the break-glass flag in a later release does not lock out the only accounts
    able to grant roles back.

    Does not commit: the caller owns the transaction, so the grant lands with
    the user row or not at all.
    """
    granted: list[str] = []
    wanted = []

    default_role = get_settings().DEFAULT_USER_ROLE
    if default_role:
        wanted.append(default_role)
    if user.is_superuser:
        wanted.append("admin")

    for name in wanted:
        role = session.exec(select(Role).where(Role.name == name)).first()
        if role is None:
            logger.error(
                "cannot grant %r to %s: no such role. The catalog is seeded at "
                "startup, so this means seeding did not run or the name is "
                "wrong. The user will hold no permissions until an "
                "administrator grants one.",
                name, user.username,
            )
            continue
        already = session.exec(
            select(UserRole).where(UserRole.user_id == user.id,
                                   UserRole.role_id == role.id)
        ).first()
        if already:
            continue
        session.add(UserRole(user_id=user.id, role_id=role.id,
                             source=GrantSource.BOOTSTRAP))
        granted.append(name)

    return granted


def get_role_or_404(session: Session, name: str) -> Role:
    role = session.exec(select(Role).where(Role.name == name)).first()
    if role is None:
        raise _not_found(f"No role named {name}")
    return role


def get_user_or_404(session: Session, username: str) -> User:
    user = session.exec(select(User).where(User.username == username)).first()
    if user is None:
        raise _not_found(f"No user named {username}")
    return user


# --- roles ----------------------------------------------------------------

def create_role(
    session: Session, *, name: str, display_name: str, description: str | None,
    scope: RoleScope, permissions: list[str],
) -> Role:
    if session.exec(select(Role).where(Role.name == name)).first():
        raise _conflict(f"A role named {name} already exists")
    validate_permissions(permissions, scope)

    role = Role(name=name, display_name=display_name, description=description,
                scope=scope, is_builtin=False)
    session.add(role)
    session.flush()
    for permission in set(permissions):
        session.add(RolePermission(role_id=role.id, permission=permission))
    session.commit()
    session.refresh(role)
    return role


def set_role_permissions(
    session: Session, role: Role, permissions: list[str]
) -> Role:
    """
    Replace a role's permission set.

    Builtin roles are code-defined and re-derived on every deploy, so editing one
    here would be silently undone at the next startup. Rejected rather than
    accepted-and-reverted.
    """
    if role.is_builtin:
        raise _conflict(
            f"{role.name} is a builtin role; its permissions come from "
            "api/rbac/roles.py and are re-derived on deploy. Create a custom "
            "role instead."
        )
    validate_permissions(permissions, role.scope)

    existing = {
        rp.permission: rp
        for rp in session.exec(
            select(RolePermission).where(RolePermission.role_id == role.id)
        ).all()
    }
    wanted = set(permissions)
    for permission in wanted - set(existing):
        session.add(RolePermission(role_id=role.id, permission=permission))
    for permission in set(existing) - wanted:
        session.delete(existing[permission])

    role.updated_at = datetime.now(timezone.utc)
    session.add(role)
    session.commit()
    session.refresh(role)
    return role


def delete_role(session: Session, role: Role) -> None:
    if role.is_builtin:
        raise _conflict(f"{role.name} is a builtin role and cannot be deleted")

    global_grants = session.exec(
        select(func.count()).select_from(UserRole).where(UserRole.role_id == role.id)
    ).one()
    project_grants = session.exec(
        select(func.count()).select_from(ProjectMember)
        .where(ProjectMember.role_id == role.id)
    ).one()
    if global_grants or project_grants:
        raise _conflict(
            f"{role.name} is still granted to {global_grants} user(s) and "
            f"{project_grants} project member(s); revoke those first"
        )

    session.delete(role)
    session.commit()


# --- global grants --------------------------------------------------------

def grant_global_role(
    session: Session, user: User, role: Role, granted_by: uuid.UUID | None
) -> bool:
    """Returns False when the user already held it. Idempotent by design."""
    if role.scope is not RoleScope.GLOBAL:
        raise _bad_request(
            f"{role.name} is a project role; grant it through the project "
            "membership endpoints"
        )
    existing = session.exec(
        select(UserRole).where(UserRole.user_id == user.id,
                               UserRole.role_id == role.id)
    ).first()
    if existing:
        return False
    session.add(UserRole(user_id=user.id, role_id=role.id,
                         granted_by=granted_by, source=GrantSource.MANUAL))
    session.commit()
    return True


def revoke_global_role(
    session: Session, user: User, role: Role, acting_user_id: uuid.UUID | None
) -> None:
    grant = session.exec(
        select(UserRole).where(UserRole.user_id == user.id,
                               UserRole.role_id == role.id)
    ).first()
    if grant is None:
        raise _not_found(f"{user.username} does not hold {role.name}")

    _guard_last_role_manager(session, user, role, acting_user_id)

    session.delete(grant)
    session.commit()


def _guard_last_role_manager(
    session: Session, user: User, role: Role, acting_user_id: uuid.UUID | None
) -> None:
    """
    Refuse to remove the last non-superuser holder of role:manage.

    Losing it means nobody can grant anything back without a superuser or direct
    database access, so this is worth blocking rather than warning about.
    """
    grants_role_manage = session.exec(
        select(RolePermission).where(
            RolePermission.role_id == role.id,
            RolePermission.permission == str(Permission.ROLE_MANAGE),
        )
    ).first()
    if not grants_role_manage:
        return

    holders = session.exec(
        select(UserRole.user_id)
        .join(RolePermission, RolePermission.role_id == UserRole.role_id)
        .join(User, User.id == UserRole.user_id)
        .where(
            RolePermission.permission == str(Permission.ROLE_MANAGE),
            User.is_superuser.is_(False),
            User.is_active.is_(True),
        )
    ).all()
    if set(holders) <= {user.id}:
        raise _conflict(
            f"{user.username} is the last non-superuser holder of "
            f"{Permission.ROLE_MANAGE}; revoking it would leave nobody able to "
            "manage roles. Grant it to someone else first."
        )


# --- project membership ---------------------------------------------------

def set_project_member(
    session: Session, project_id: uuid.UUID, user: User, role: Role,
    granted_by: uuid.UUID | None,
) -> tuple[ProjectMember, bool]:
    """Add or change a member. Returns (member, created)."""
    if role.scope is not RoleScope.PROJECT:
        raise _bad_request(
            f"{role.name} is a global role; grant it through /rbac/users"
        )

    existing = session.exec(
        select(ProjectMember).where(ProjectMember.project_id == project_id,
                                    ProjectMember.user_id == user.id)
    ).first()

    if existing:
        if existing.role_id != role.id:
            _guard_last_owner(session, project_id, existing, changing_to=role)
            existing.role_id = role.id
            existing.granted_by = granted_by
            existing.granted_at = datetime.now(timezone.utc)
            session.add(existing)
            session.commit()
            session.refresh(existing)
        return existing, False

    member = ProjectMember(project_id=project_id, user_id=user.id, role_id=role.id,
                           granted_by=granted_by, source=GrantSource.MANUAL)
    session.add(member)
    session.commit()
    session.refresh(member)
    return member, True


def remove_project_member(
    session: Session, project_id: uuid.UUID, user: User
) -> None:
    member = session.exec(
        select(ProjectMember).where(ProjectMember.project_id == project_id,
                                    ProjectMember.user_id == user.id)
    ).first()
    if member is None:
        raise _not_found(f"{user.username} is not a member of this project")

    _guard_last_owner(session, project_id, member, changing_to=None)

    session.delete(member)
    session.commit()


def _guard_last_owner(
    session: Session, project_id: uuid.UUID, member: ProjectMember,
    changing_to: Role | None,
) -> None:
    """
    Refuse to leave a project with no owner.

    An ownerless project cannot have its membership changed by anyone short of a
    superuser, which is how projects quietly become unadministrable.
    """
    owner_role = session.exec(
        select(Role).where(Role.name == "project_owner")
    ).first()
    if owner_role is None or member.role_id != owner_role.id:
        return
    if changing_to is not None and changing_to.id == owner_role.id:
        return

    owner_count = session.exec(
        select(func.count()).select_from(ProjectMember).where(
            ProjectMember.project_id == project_id,
            ProjectMember.role_id == owner_role.id,
        )
    ).one()
    if owner_count <= 1:
        raise _conflict(
            "This is the project's last owner; the project would be left with "
            "nobody able to manage its membership. Add another owner first."
        )


# --- administration reads -------------------------------------------------

_USER_SORT_FIELDS = {
    "username": User.username,
    "email": User.email,
    "full_name": User.full_name,
    "created_at": User.created_at,
    "last_login": User.last_login,
}


def _global_roles_by_user(
    session: Session, user_ids: list[uuid.UUID]
) -> dict[uuid.UUID, list[str]]:
    """
    Role names for a page of users, in one query.

    Per-user calls to global_role_names would be a query per row, which is the
    kind of thing that looks fine on a 20-row page and is not fine on a roster
    that grows with the organisation.
    """
    if not user_ids:
        return {}
    rows = session.exec(
        select(UserRole.user_id, Role.name)
        .join(Role, Role.id == UserRole.role_id)
        .where(col(UserRole.user_id).in_(user_ids))
        .order_by(Role.name)
    ).all()
    grouped: dict[uuid.UUID, list[str]] = {}
    for user_id, role_name in rows:
        grouped.setdefault(user_id, []).append(role_name)
    return grouped


def list_users(
    session: Session, *, skip: int, limit: int, q: str | None = None,
    role: str | None = None, is_active: bool | None = None,
    sort_by: str = "username", sort_order: str = "asc",
) -> UsersAdminPublic:
    """
    The administrative user roster.

    Distinct from api.users.services.search_users, which backs the user
    *picker*: that one may answer from LDAP, requires a query string, and hides
    deactivated accounts, all correct for choosing somebody to grant a role to
    and all wrong for administering the accounts that exist. This reads the local
    users table only, and a deactivated account is precisely what an
    administrator came here to find.
    """
    filters = []
    if q:
        term = f"%{q}%"
        filters.append(
            or_(
                col(User.username).ilike(term),
                col(User.email).ilike(term),
                col(User.full_name).ilike(term),
            )
        )
    if is_active is not None:
        filters.append(col(User.is_active).is_(is_active))
    if role is not None:
        # Validated first so a typo is a 404 naming the role, not an empty page
        # that reads as "nobody holds this".
        role_row = get_role_or_404(session, role)
        filters.append(
            col(User.id).in_(
                select(UserRole.user_id).where(UserRole.role_id == role_row.id)
            )
        )

    total_count = session.exec(
        select(func.count()).select_from(User).where(*filters)
    ).one()

    sort_field = _USER_SORT_FIELDS.get(sort_by, User.username)
    direction = sort_field.asc() if sort_order == "asc" else sort_field.desc()

    users = session.exec(
        select(User)
        .where(*filters)
        # Tie-break on the unique column: the sortable fields are all nullable
        # or non-unique, and an unstable order makes rows appear to move between
        # pages as somebody pages through.
        .order_by(direction, User.username.asc())
        .offset(skip)
        .limit(limit)
    ).all()

    roles_by_user = _global_roles_by_user(session, [u.id for u in users])

    return UsersAdminPublic(
        data=[
            UserAdminPublic(
                username=user.username,
                email=user.email,
                full_name=user.full_name,
                is_active=user.is_active,
                is_verified=user.is_verified,
                is_superuser=user.is_superuser,
                created_at=user.created_at,
                last_login=user.last_login,
                global_roles=roles_by_user.get(user.id, []),
            )
            for user in users
        ],
        total_items=total_count,
        skip=skip,
        limit=limit,
        has_next=(skip + limit) < total_count,
        has_prev=skip > 0,
    )


def get_user_access(session: Session, user: User) -> UserAccessPublic:
    """
    One user's whole authorization footprint.

    Effective permissions come from AuthzContext, the same resolver the route
    guards use, rather than a second union computed here -- a reporting path with
    its own implementation eventually disagrees with the enforcing one, and it
    lies during an incident, which is the only time anyone reads it.
    """
    authz = AuthzContext.for_user(session, user)

    rows = session.exec(
        select(Project.project_id, Project.name, Role.name,
               ProjectMember.granted_at, ProjectMember.source)
        .join(ProjectMember, ProjectMember.project_id == Project.id)
        .join(Role, Role.id == ProjectMember.role_id)
        .where(ProjectMember.user_id == user.id)
        .order_by(Project.project_id)
    ).all()

    return UserAccessPublic(
        username=user.username,
        email=user.email,
        full_name=user.full_name,
        is_active=user.is_active,
        is_verified=user.is_verified,
        is_superuser=user.is_superuser,
        global_roles=global_role_names(session, user.id),
        global_permissions=authz.effective_permissions(),
        project_memberships=[
            ProjectMembershipPublic(
                project_id=project_id,
                project_name=project_name,
                role=role_name,
                granted_at=granted_at,
                source=str(source.value),
            )
            for project_id, project_name, role_name, granted_at, source in rows
        ],
    )


# --- user status flags ----------------------------------------------------

def update_user_flags(
    session: Session, user: User, *, acting_user: User,
    is_active: bool | None = None, is_verified: bool | None = None,
    is_superuser: bool | None = None,
) -> User:
    """
    Set is_active, is_verified and is_superuser. None means leave alone.

    These three are grouped in one route because they are one decision -- may
    this account be used, and how far -- and because all three need the same
    guardrails. The guardrails matter more than they look: get_current_active_user
    requires BOTH is_active and is_verified, so clearing either one locks the
    account out entirely, and the two ways to make the platform unadministrable
    are to lock out its last superuser or its last role manager.
    """
    locking_out = is_active is False or is_verified is False

    if is_superuser is not None and not acting_user.is_superuser:
        # Load-bearing: the route is guarded by user:manage alone now, so this
        # is the only thing keeping the break-glass flag behind superuser.
        # docs/RBAC.md is explicit that granting it takes user:manage AND
        # superuser. It lives on the mutation rather than the route because the
        # rule belongs to the change, not to one way of reaching it.
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            detail="Setting is_superuser requires being a superuser, not only "
                   f"{Permission.USER_MANAGE}",
        )

    if user.id == acting_user.id:
        if locking_out:
            raise _conflict(
                "You cannot deactivate or unverify your own account: both are "
                "required to authenticate, so this would lock you out."
            )
        if is_superuser is False:
            raise _conflict(
                "You cannot remove your own superuser flag. Ask another "
                "superuser, so that the decision has a second person in it."
            )

    if user.is_superuser and (locking_out or is_superuser is False):
        _guard_last_superuser(session, user)

    if locking_out:
        _guard_last_role_manager_lockout(session, user)

    if is_active is not None:
        user.is_active = is_active
    if is_verified is not None:
        user.is_verified = is_verified
    if is_superuser is not None:
        user.is_superuser = is_superuser

    user.updated_at = datetime.now(timezone.utc)
    session.add(user)
    session.commit()
    session.refresh(user)
    return user


def _guard_last_superuser(session: Session, user: User) -> None:
    """
    Refuse to leave the platform with no usable superuser.

    Usable means active and verified, because get_current_active_user requires
    both -- counting rows with is_superuser set would happily leave a deployment
    whose only administrator cannot log in.
    """
    others = session.exec(
        select(func.count()).select_from(User).where(
            User.id != user.id,
            col(User.is_superuser).is_(True),
            col(User.is_active).is_(True),
            col(User.is_verified).is_(True),
        )
    ).one()
    if others == 0:
        raise _conflict(
            f"{user.username} is the only superuser who can still sign in. "
            "Promote somebody else first, or there would be no way back in "
            "short of direct database access."
        )


def _role_manage_holder_ids(session: Session) -> set[uuid.UUID]:
    """
    Users who can grant roles without being superusers.

    Superusers are excluded because they hold everything implicitly; they are the
    fallback these guards exist to avoid depending on.
    """
    rows = session.exec(
        select(UserRole.user_id)
        .join(RolePermission, RolePermission.role_id == UserRole.role_id)
        .join(User, User.id == UserRole.user_id)
        .where(
            RolePermission.permission == str(Permission.ROLE_MANAGE),
            User.is_superuser.is_(False),
            User.is_active.is_(True),
        )
    ).all()
    return set(rows)


def _guard_last_role_manager_lockout(session: Session, user: User) -> None:
    """
    Deactivating or unverifying is a revocation of everything the user holds, so
    it has to answer to the same rule as revoking role:manage directly.
    """
    holders = _role_manage_holder_ids(session)
    if user.id in holders and holders <= {user.id}:
        raise _conflict(
            f"{user.username} is the last non-superuser holder of "
            f"{Permission.ROLE_MANAGE}; locking the account would leave nobody "
            "able to manage roles. Grant it to someone else first."
        )
