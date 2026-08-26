"""
RBAC tables: roles, their permissions, and the two kinds of grant.

Four tables. Roles are rows so administrators can compose custom ones; the
permissions they contain are validated against the code-level catalog in
api/rbac/permissions.py on every write.

Two grant tables rather than one polymorphic `role_assignment`, because a single
table could not carry a real foreign key to `project`, would invite `scope_type`
string typos, and would need a partial unique index MySQL does not support.
"Who is on this project" is also a product concept with a UI behind it, not only
an authorization artifact.

Note on naming: `role` as a *column* already exists elsewhere with unrelated
meanings -- FileProject.role holds "samplesheet", FileSample.role holds
"tumor"/"normal". An RBAC role is always this `role` table or a `role_id` column.

Cascades are declared at the database level rather than only in the ORM. A user
removed by direct SQL must not leave grants behind, and authorization data is
exactly where an orphan row is dangerous rather than untidy.

See docs/RBAC.md for the schema rationale.
"""

import uuid
from datetime import datetime, timezone
from enum import Enum

from pydantic import ConfigDict
from sqlmodel import Field, SQLModel, UniqueConstraint

from api.rbac.roles import RoleScope  # noqa: F401  (re-exported for convenience)


class GrantSource(str, Enum):
    """
    How a grant came to exist.

    Nothing sets DIRECTORY in v1. It exists so a future AD or LDAP sync job can
    reconcile only the rows it owns -- deleting stale directory-derived grants
    without touching anything an administrator granted by hand. Adding the column
    later would mean backfilling provenance that no longer exists.
    """

    MANUAL = "manual"
    BOOTSTRAP = "bootstrap"
    MIGRATION = "migration"
    DIRECTORY = "directory"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Role(SQLModel, table=True):
    """A named set of permissions, grantable in one plane."""

    __tablename__ = "role"

    id: uuid.UUID | None = Field(default_factory=uuid.uuid4, primary_key=True)

    name: str = Field(unique=True, index=True, max_length=64)
    display_name: str = Field(max_length=128)
    description: str | None = Field(default=None, max_length=512)

    # GLOBAL roles apply platform-wide; PROJECT roles are granted per project and
    # may only contain project-scopable permissions.
    scope: RoleScope = Field(index=True)

    # Seeded from api/rbac/roles.py. Builtin roles cannot be renamed, rescoped or
    # deleted, and their permission set is re-derived from code on every sync.
    is_builtin: bool = Field(default=False)

    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)

    model_config = ConfigDict(from_attributes=True)


class RolePermission(SQLModel, table=True):
    """One permission held by one role."""

    __tablename__ = "role_permission"
    __table_args__ = (
        UniqueConstraint("role_id", "permission", name="uq_role_permission"),
    )

    id: uuid.UUID | None = Field(default_factory=uuid.uuid4, primary_key=True)
    role_id: uuid.UUID = Field(
        foreign_key="role.id", index=True, ondelete="CASCADE"
    )
    # The value of a Permission enum member. Stored as a string so the catalog can
    # gain members without a migration; validated against the enum on write.
    permission: str = Field(max_length=64)


class UserRole(SQLModel, table=True):
    """
    A global role grant.

    Additive: a user may hold several. `member` plus `service_account` is a
    legitimate combination.
    """

    __tablename__ = "user_role"
    __table_args__ = (
        UniqueConstraint("user_id", "role_id", name="uq_user_role"),
    )

    id: uuid.UUID | None = Field(default_factory=uuid.uuid4, primary_key=True)
    user_id: uuid.UUID = Field(
        foreign_key="users.id", index=True, ondelete="CASCADE"
    )
    role_id: uuid.UUID = Field(
        foreign_key="role.id", index=True, ondelete="CASCADE"
    )

    source: GrantSource = Field(default=GrantSource.MANUAL, max_length=16)
    granted_by: uuid.UUID | None = Field(default=None, foreign_key="users.id")
    granted_at: datetime = Field(default_factory=_utcnow)


class ProjectMember(SQLModel, table=True):
    """
    A project-scoped role grant. Exactly one role per user per project.

    Exclusive rather than additive because the three project roles form a total
    order (viewer, contributor, owner), so stacking them would add only ambiguity.
    If additive grants are ever needed, relax the unique constraint to include
    role_id -- the resolver already unions, so no logic changes.

    project_id references project.id (the UUID surrogate), not project.project_id
    (the business key). get_validated_project already loads the whole row before
    any permission check, so nothing is saved by the string key, and a renamed
    business key must never be able to orphan an authorization row.
    """

    __tablename__ = "project_member"
    __table_args__ = (
        UniqueConstraint("project_id", "user_id", name="uq_project_member"),
    )

    id: uuid.UUID | None = Field(default_factory=uuid.uuid4, primary_key=True)
    project_id: uuid.UUID = Field(
        foreign_key="project.id", index=True, ondelete="CASCADE"
    )
    user_id: uuid.UUID = Field(
        foreign_key="users.id", index=True, ondelete="CASCADE"
    )
    # RESTRICT, not CASCADE: deleting a role that is still granted somewhere
    # should fail loudly rather than silently revoking people's access.
    role_id: uuid.UUID = Field(foreign_key="role.id", ondelete="RESTRICT")

    source: GrantSource = Field(default=GrantSource.MANUAL, max_length=16)
    granted_by: uuid.UUID | None = Field(default=None, foreign_key="users.id")
    granted_at: datetime = Field(default_factory=_utcnow)


# --- Read models ----------------------------------------------------------

class PermissionPublic(SQLModel):
    """One catalog entry, as returned by GET /rbac/permissions."""

    permission: str
    resource: str
    description: str
    project_scopable: bool
    risk: str


class RolePublic(SQLModel):
    """A role and the permissions it holds."""

    id: uuid.UUID
    name: str
    display_name: str
    description: str | None
    scope: RoleScope
    is_builtin: bool
    permissions: list[str]


class RoleCreate(SQLModel):
    """Request body for creating a custom role."""

    name: str = Field(max_length=64)
    display_name: str = Field(max_length=128)
    description: str | None = Field(default=None, max_length=512)
    scope: RoleScope
    permissions: list[str] = []


class RolePermissionsUpdate(SQLModel):
    """Replace a role's permission set."""

    permissions: list[str]


class GrantRoleRequest(SQLModel):
    """Grant a global role to a user."""

    role: str


class ProjectMemberRequest(SQLModel):
    """Add or change a project member."""

    username: str
    role: str


class ProjectMemberPublic(SQLModel):
    """A project membership, as returned by the members endpoints."""

    username: str
    role: str
    granted_at: datetime
    source: str
