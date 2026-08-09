"""
Role and grant mutations.

Every write validates against the code-level catalog, because a role holding a
permission no route checks is not a capability -- it is a lie about one. The
guardrails here exist to stop the two mistakes that are hard to undo: revoking
your own ability to grant, and orphaning a project nobody can administer.
"""

import uuid
from datetime import datetime, timezone

from fastapi import HTTPException, status
from sqlmodel import Session, func, select

from api.auth.models import User
from api.rbac.models import GrantSource, ProjectMember, Role, RolePermission, UserRole
from api.rbac.permissions import ALL_PERMISSIONS, PROJECT_SCOPABLE, Permission
from api.rbac.roles import RoleScope


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
