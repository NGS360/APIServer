"""
Workflow Service

CRUD operations for Workflow, WorkflowVersion, WorkflowVersionAlias,
and WorkflowDeployment entities.
"""
from uuid import UUID

from fastapi import HTTPException, status
from sqlmodel import Session, select
from sqlalchemy import func

from api.platforms.models import Platform
from api.workflow.models import (
    Attribute,
    Workflow,
    WorkflowAttribute,
    WorkflowAliasSummary,
    WorkflowCreate,
    WorkflowPublic,
    WorkflowDeployment,
    WorkflowDeploymentCreate,
    WorkflowDeploymentPublic,
    WorkflowVersion,
    WorkflowVersionAlias,
    WorkflowVersionAttribute,
    WorkflowVersionCreate,
    WorkflowVersionPublic,
    WorkflowVersionSummary,
    WorkflowVersionAliasPublic,
    WorkflowVersionAliasSet,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse_uuid(value: str, label: str = "id") -> UUID:
    """Parse a string to UUID, raising 400 on invalid format."""
    try:
        return UUID(value)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid UUID format for {label}: '{value}'",
        ) from exc


def _validate_engine(session: Session, engine: str) -> None:
    """Verify that ``engine`` matches a registered Platform name."""
    platform = session.exec(
        select(Platform).where(Platform.name == engine)
    ).first()
    if not platform:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Engine '{engine}' is not a registered platform. "
                "Create it via POST /platforms first."
            ),
        )


# ---------------------------------------------------------------------------
# Workflow CRUD
# ---------------------------------------------------------------------------

def create_workflow(
    session: Session,
    workflow_in: WorkflowCreate,
    created_by: str,
) -> Workflow:
    """Create a workflow identity with optional attributes."""
    workflow = Workflow(
        name=workflow_in.name,
        created_by=created_by,
    )

    session.add(workflow)
    session.flush()

    # Handle attribute mapping
    if workflow_in.attributes:
        # Prevent duplicate keys
        seen: set[str] = set()
        keys = [attr.key for attr in workflow_in.attributes]
        dups = [k for k in keys if k in seen or seen.add(k)]
        if dups:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    f"Duplicate keys ({', '.join(dups)}) "
                    "are not allowed in workflow attributes."
                ),
            )

        workflow_attributes = [
            WorkflowAttribute(
                workflow_id=workflow.id,
                key=attr.key,
                value=attr.value,
            )
            for attr in workflow_in.attributes
        ]
        session.add_all(workflow_attributes)

    session.commit()
    session.refresh(workflow)
    return workflow


def get_workflows(
    session: Session,
    page: int = 1,
    per_page: int = 20,
    sort_by: str = "name",
    sort_order: str = "asc",
) -> list[Workflow]:
    """Returns a paginated list of workflows."""
    valid_sort_fields = {
        "id": Workflow.id,
        "name": Workflow.name,
        "created_at": Workflow.created_at,
    }
    if sort_by not in valid_sort_fields:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Invalid sort_by field '{sort_by}'. "
                f"Valid fields are: "
                f"{', '.join(valid_sort_fields.keys())}."
            ),
        )

    sort_column = valid_sort_fields[sort_by]
    if sort_order == "desc":
        sort_column = sort_column.desc()

    offset = (page - 1) * per_page

    workflows = session.exec(
        select(Workflow)
        .order_by(sort_column)
        .offset(offset)
        .limit(per_page)
    ).all()
    return workflows


def get_workflow_by_id(
    session: Session, workflow_id: str,
) -> Workflow:
    """Returns a single workflow by its UUID."""
    wf_uuid = _parse_uuid(workflow_id, "workflow_id")
    workflow = session.exec(
        select(Workflow).where(Workflow.id == wf_uuid)
    ).first()
    if not workflow:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Workflow with id '{workflow_id}' not found.",
        )
    return workflow


def workflow_to_public(workflow: Workflow) -> WorkflowPublic:
    """Convert a Workflow ORM object to its public representation."""
    attributes = None
    if workflow.attributes:
        attributes = [
            Attribute(key=a.key, value=a.value)
            for a in workflow.attributes
        ]

    versions = None
    if workflow.versions:
        versions = [
            WorkflowVersionSummary(
                id=v.id,
                version=v.version,
                definition_uri=v.definition_uri,
                created_at=v.created_at,
            )
            for v in workflow.versions
        ]

    aliases = None
    if workflow.aliases:
        aliases = [
            WorkflowAliasSummary(
                alias=a.alias,
                workflow_version_id=a.workflow_version_id,
                version=a.workflow_version.version,
            )
            for a in workflow.aliases
        ]

    return WorkflowPublic(
        id=workflow.id,
        name=workflow.name,
        created_at=workflow.created_at,
        created_by=workflow.created_by,
        attributes=attributes,
        versions=versions,
        aliases=aliases,
    )


# ---------------------------------------------------------------------------
# WorkflowVersion CRUD
# ---------------------------------------------------------------------------

def create_workflow_version(
    session: Session,
    workflow_id: str,
    version_in: WorkflowVersionCreate,
    created_by: str,
) -> WorkflowVersion:
    """Create a new version for a workflow."""
    workflow = get_workflow_by_id(session, workflow_id)

    # Build the query
    stmt = (
        select(func.coalesce(func.max(WorkflowVersion.version), 0))
        .where(WorkflowVersion.workflow_id == workflow.id)
    )
    # Apply FOR UPDATE only on databases that support it
    dialect = session.bind.dialect.name
    if dialect in ("postgresql", "mysql"):
        stmt = stmt.with_for_update()

    max_version = session.exec(stmt).one()
    next_version = max_version + 1

    version = WorkflowVersion(
        workflow_id=workflow.id,
        version=next_version,
        definition_uri=version_in.definition_uri,
        created_by=created_by,
    )
    session.add(version)
    session.flush() # ensure version row exists in DB

    # Handle attribute mapping
    if version_in.attributes:
        # Prevent duplicate keys
        seen: set[str] = set()
        keys = [attr.key for attr in version_in.attributes]
        dups = [k for k in keys if k in seen or seen.add(k)]
        if dups:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    f"Duplicate keys ({', '.join(dups)}) "
                    "are not allowed in workflow version attributes."
                ),
            )

        version_attributes = [
            WorkflowVersionAttribute(
                workflow_version_id=version.id,
                key=attr.key,
                value=attr.value,
            )
            for attr in version_in.attributes
        ]
        session.add_all(version_attributes)

    session.commit()
    session.refresh(version)
    return version


def get_workflow_versions(
    session: Session, workflow_id: str,
) -> list[WorkflowVersion]:
    """List all versions of a workflow."""
    workflow = get_workflow_by_id(session, workflow_id)
    versions = session.exec(
        select(WorkflowVersion)
        .where(WorkflowVersion.workflow_id == workflow.id)
        .order_by(WorkflowVersion.created_at.desc())
    ).all()
    return versions


def get_workflow_version_by_id(
    session: Session, version_id: str,
) -> WorkflowVersion:
    """Get a single workflow version by its UUID."""
    ver_uuid = _parse_uuid(version_id, "version_id")
    version = session.exec(
        select(WorkflowVersion)
        .where(WorkflowVersion.id == ver_uuid)
    ).first()
    if not version:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=(
                f"Workflow version with id "
                f"'{version_id}' not found."
            ),
        )
    return version


def workflow_version_to_public(
    version: WorkflowVersion,
) -> WorkflowVersionPublic:
    """Convert a WorkflowVersion ORM object to public."""
    deployments = None
    if version.deployments:
        deployments = [
            WorkflowDeploymentPublic(
                id=r.id,
                workflow_version_id=r.workflow_version_id,
                engine=r.engine,
                external_id=r.external_id,
                created_at=r.created_at,
                created_by=r.created_by,
            )
            for r in version.deployments
        ]

    attributes = None
    if version.attributes:
        attributes = [
            Attribute(key=a.key, value=a.value)
            for a in version.attributes
        ]

    return WorkflowVersionPublic(
        id=version.id,
        workflow_id=version.workflow_id,
        version=version.version,
        definition_uri=version.definition_uri,
        created_at=version.created_at,
        created_by=version.created_by,
        deployments=deployments,
        attributes=attributes,
    )


# ---------------------------------------------------------------------------
# WorkflowVersionAlias CRUD
# ---------------------------------------------------------------------------

def set_workflow_version_alias(
    session: Session,
    workflow_id: str,
    alias: str,
    alias_in: WorkflowVersionAliasSet,
    created_by: str,
) -> WorkflowVersionAlias:
    """Set or move an alias to a specific workflow version."""
    workflow = get_workflow_by_id(session, workflow_id)

    # Verify the target version exists and belongs to this workflow
    version = session.exec(
        select(WorkflowVersion).where(
            WorkflowVersion.id == alias_in.workflow_version_id,
            WorkflowVersion.workflow_id == workflow.id,
        )
    ).first()
    if not version:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=(
                f"Workflow version "
                f"'{alias_in.workflow_version_id}' not found "
                f"for workflow '{workflow_id}'."
            ),
        )

    # Upsert — replace existing alias or create new one
    existing = session.exec(
        select(WorkflowVersionAlias).where(
            WorkflowVersionAlias.workflow_id == workflow.id,
            WorkflowVersionAlias.alias == alias,
        )
    ).first()

    if existing:
        existing.workflow_version_id = version.id
        existing.created_by = created_by
        session.add(existing)
        session.commit()
        session.refresh(existing)
        return existing

    alias_record = WorkflowVersionAlias(
        workflow_id=workflow.id,
        alias=alias,
        workflow_version_id=version.id,
        created_by=created_by,
    )
    session.add(alias_record)
    session.commit()
    session.refresh(alias_record)
    return alias_record


def get_workflow_version_aliases(
    session: Session,
    workflow_id: str,
    alias: str | None = None,
) -> list[WorkflowVersionAlias]:
    """List aliases for a workflow, optionally filtered by alias name."""
    workflow = get_workflow_by_id(session, workflow_id)
    stmt = select(WorkflowVersionAlias).where(
        WorkflowVersionAlias.workflow_id == workflow.id,
    )
    if alias is not None:
        stmt = stmt.where(WorkflowVersionAlias.alias == alias)
    aliases = session.exec(stmt).all()
    return aliases


def delete_workflow_version_alias(
    session: Session,
    workflow_id: str,
    alias: str,
) -> None:
    """Remove an alias from a workflow."""
    workflow = get_workflow_by_id(session, workflow_id)
    existing = session.exec(
        select(WorkflowVersionAlias).where(
            WorkflowVersionAlias.workflow_id == workflow.id,
            WorkflowVersionAlias.alias == alias,
        )
    ).first()
    if not existing:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=(
                f"Alias '{alias}' not found "
                f"for workflow '{workflow_id}'."
            ),
        )
    session.delete(existing)
    session.commit()


def alias_to_public(
    alias: WorkflowVersionAlias,
) -> WorkflowVersionAliasPublic:
    """Convert a WorkflowVersionAlias ORM to public."""
    return WorkflowVersionAliasPublic(
        id=alias.id,
        workflow_id=alias.workflow_id,
        alias=alias.alias,
        workflow_version_id=alias.workflow_version_id,
        version=alias.workflow_version.version,
        created_at=alias.created_at,
        created_by=alias.created_by,
    )


# ---------------------------------------------------------------------------
# WorkflowDeployment CRUD
# ---------------------------------------------------------------------------

def create_workflow_deployment(
    session: Session,
    workflow_id: str,
    version_id: str,
    deployment_in: WorkflowDeploymentCreate,
    created_by: str,
) -> WorkflowDeployment:
    """Deploy a workflow version on a specific platform."""
    # Verify workflow exists
    workflow = get_workflow_by_id(session, workflow_id)

    # Verify version exists and belongs to this workflow
    ver_uuid = _parse_uuid(version_id, "version_id")
    version = session.exec(
        select(WorkflowVersion).where(
            WorkflowVersion.id == ver_uuid,
            WorkflowVersion.workflow_id == workflow.id,
        )
    ).first()
    if not version:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=(
                f"Version '{version_id}' not found "
                f"for workflow '{workflow_id}'."
            ),
        )

    # Verify engine is a registered platform
    _validate_engine(session, deployment_in.engine)

    # Check for duplicate (version_id, engine)
    existing = session.exec(
        select(WorkflowDeployment).where(
            WorkflowDeployment.workflow_version_id == version.id,
            WorkflowDeployment.engine == deployment_in.engine,
        )
    ).first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"Version '{version_id}' is already deployed "
                f"on engine '{deployment_in.engine}'."
            ),
        )

    deployment = WorkflowDeployment(
        workflow_version_id=version.id,
        engine=deployment_in.engine,
        external_id=deployment_in.external_id,
        created_by=created_by,
    )

    session.add(deployment)
    session.commit()
    session.refresh(deployment)
    return deployment


def get_workflow_deployments(
    session: Session,
    workflow_id: str,
    version_id: str,
    engine: str | None = None,
) -> list[WorkflowDeployment]:
    """List platform deployments for a workflow version."""
    workflow = get_workflow_by_id(session, workflow_id)
    ver_uuid = _parse_uuid(version_id, "version_id")
    version = session.exec(
        select(WorkflowVersion).where(
            WorkflowVersion.id == ver_uuid,
            WorkflowVersion.workflow_id == workflow.id,
        )
    ).first()
    if not version:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=(
                f"Version '{version_id}' not found "
                f"for workflow '{workflow_id}'."
            ),
        )
    stmt = select(WorkflowDeployment).where(
        WorkflowDeployment.workflow_version_id == version.id,
    )
    if engine is not None:
        stmt = stmt.where(WorkflowDeployment.engine == engine)
    deployments = session.exec(stmt).all()
    return deployments


def get_workflow_deployments_for_workflow(
    session: Session,
    workflow_id: str,
    alias: str | None = None,
    engine: str | None = None,
) -> list[WorkflowDeployment]:
    """List deployments across versions of a workflow.

    Optional filters:
    - alias: resolve the alias to a version and restrict to that version
    - engine: restrict to a specific platform
    """
    workflow = get_workflow_by_id(session, workflow_id)

    if alias is not None:
        # Resolve alias → version_id
        alias_record = session.exec(
            select(WorkflowVersionAlias).where(
                WorkflowVersionAlias.workflow_id == workflow.id,
                WorkflowVersionAlias.alias == alias,
            )
        ).first()
        if not alias_record:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=(
                    f"Alias '{alias}' is not set "
                    f"for workflow '{workflow_id}'."
                ),
            )
        version_ids = [alias_record.workflow_version_id]
    else:
        # All versions of this workflow
        version_ids = session.exec(
            select(WorkflowVersion.id).where(
                WorkflowVersion.workflow_id == workflow.id,
            )
        ).all()
        if not version_ids:
            return []

    stmt = select(WorkflowDeployment).where(
        WorkflowDeployment.workflow_version_id.in_(version_ids),
    )
    if engine is not None:
        stmt = stmt.where(WorkflowDeployment.engine == engine)

    return session.exec(stmt).all()


def delete_workflow_deployment(
    session: Session,
    workflow_id: str,
    version_id: str,
    deployment_id: str,
) -> None:
    """Remove a workflow platform deployment."""
    workflow = get_workflow_by_id(session, workflow_id)
    ver_uuid = _parse_uuid(version_id, "version_id")
    version = session.exec(
        select(WorkflowVersion).where(
            WorkflowVersion.id == ver_uuid,
            WorkflowVersion.workflow_id == workflow.id,
        )
    ).first()
    if not version:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=(
                f"Version '{version_id}' not found "
                f"for workflow '{workflow_id}'."
            ),
        )
    dep_uuid = _parse_uuid(deployment_id, "deployment_id")
    deployment = session.exec(
        select(WorkflowDeployment).where(
            WorkflowDeployment.id == dep_uuid,
            WorkflowDeployment.workflow_version_id == version.id,
        )
    ).first()
    if not deployment:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=(
                f"Deployment '{deployment_id}' not found "
                f"for version '{version_id}'."
            ),
        )
    session.delete(deployment)
    session.commit()
