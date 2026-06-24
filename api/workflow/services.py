"""
Workflow Service

CRUD operations for Workflow, WorkflowVersion, WorkflowVersionAlias,
and WorkflowDeployment entities.
"""
import json
from uuid import UUID

import boto3
from botocore.exceptions import ClientError, NoCredentialsError
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
from core.config import get_settings
from core.logger import logger


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
                deployments=[
                    WorkflowDeploymentPublic(
                        id=d.id,
                        workflow_version_id=d.workflow_version_id,
                        engine=d.engine,
                        external_id=d.external_id,
                        created_at=d.created_at,
                        created_by=d.created_by,
                    )
                    for d in (v.deployments or [])
                ] or None,
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
    session.flush()

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


def get_workflow_version_by_num(
    session: Session, workflow_id: str, version_num: int,
) -> WorkflowVersion:
    """Get a workflow version by its (workflow_id, version) composite key."""
    workflow = get_workflow_by_id(session, workflow_id)
    version = session.exec(
        select(WorkflowVersion).where(
            WorkflowVersion.workflow_id == workflow.id,
            WorkflowVersion.version == version_num,
        )
    ).first()
    if not version:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=(
                f"Version {version_num} not found "
                f"for workflow '{workflow_id}'."
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
    # Verify the target version exists and belongs to this workflow
    version = get_workflow_version_by_num(
        session, workflow_id, alias_in.version_num,
    )

    # Upsert — replace existing alias or create new one
    existing = session.exec(
        select(WorkflowVersionAlias).where(
            WorkflowVersionAlias.workflow_id == version.workflow_id,
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
        workflow_id=version.workflow_id,
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

def _find_existing_omics_deployment(
    session: Session,
    workflow: Workflow,
    engine: str,
) -> WorkflowDeployment | None:
    """Return the most recent Omics deployment for this Workflow, if any.

    Used to decide between Lambda action `create_workflow` (first time on Omics)
    and `create_workflow_version` (workflow already registered on Omics).
    """
    return session.exec(
        select(WorkflowDeployment)
        .join(WorkflowVersion)
        .where(
            WorkflowVersion.workflow_id == workflow.id,
            WorkflowDeployment.engine == engine,
        )
        .order_by(WorkflowVersion.version.desc())
    ).first()


def _invoke_omics_register_lambda(payload: dict) -> dict:
    """Invoke the Omics workflow-registration Lambda and return parsed body."""
    settings = get_settings()
    function_name = settings.OMICS_REGISTER_WORKFLOW_LAMBDA
    if not function_name:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=(
                "OMICS_REGISTER_WORKFLOW_LAMBDA is not configured. "
                "Set the env var to the Lambda function name."
            ),
        )

    logger.info(
        "Invoking Omics-register Lambda '%s' with action=%s",
        function_name,
        payload.get("action"),
    )

    try:
        lambda_client = boto3.client("lambda", region_name=settings.AWS_REGION)
        response = lambda_client.invoke(
            FunctionName=function_name,
            InvocationType="RequestResponse",
            Payload=json.dumps(payload),
        )
    except NoCredentialsError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="AWS credentials not found. Cannot invoke Omics Lambda.",
        ) from exc
    except ClientError as exc:
        code = exc.response["Error"]["Code"]
        msg = exc.response["Error"]["Message"]
        logger.error("Omics Lambda ClientError: %s - %s", code, msg)
        if code == "ResourceNotFoundException":
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Lambda function not found: {function_name}",
            ) from exc
        if code == "AccessDeniedException":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Access denied to Lambda function: {function_name}",
            ) from exc
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Lambda error: {msg}",
        ) from exc

    body = json.loads(response["Payload"].read().decode("utf-8"))
    logger.debug("Omics Lambda response: %s", body)

    if "FunctionError" in response:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=(
                f"Omics Lambda execution error: "
                f"{body.get('errorMessage', 'unknown')}"
            ),
        )

    if body.get("statusCode") and body["statusCode"] >= 400:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=(
                f"Omics registration failed: "
                f"{body.get('message') or body.get('error') or body}"
            ),
        )

    arn = body.get("arn")
    if not arn:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=(
                "Omics Lambda did not return an 'arn' field. "
                f"Response: {body}"
            ),
        )

    return body


def _register_workflow_on_omics(
    session: Session,
    workflow: Workflow,
    version: WorkflowVersion,
    engine: str,
) -> str:
    """Register the workflow/version on AWS HealthOmics via Lambda; return ARN."""
    prior = _find_existing_omics_deployment(session, workflow, engine)

    if prior is None:
        payload = {
            "source": "ngs360",
            "action": "create_workflow",
            "name": workflow.name,
            "cwl_s3_path": version.definition_uri,
            "id": str(version.id),
        }
    else:
        # Reuse the omics workflow id from the prior deployment's ARN.
        # ARN format: arn:aws:omics:<region>:<acct>:workflow/<id>/version/<name>
        try:
            omics_workflow_id = (
                prior.external_id.split(":workflow/")[1].split("/")[0]
            )
        except (IndexError, AttributeError) as exc:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=(
                    f"Could not parse Omics workflow id from prior "
                    f"deployment external_id '{prior.external_id}'."
                ),
            ) from exc
        payload = {
            "source": "ngs360",
            "action": "create_workflow_version",
            "omics_workflow_id": omics_workflow_id,
            "version_name": str(version.id),
            "cwl_s3_path": version.definition_uri,
            "id": str(version.id),
        }

    body = _invoke_omics_register_lambda(payload)
    return body["arn"]


def create_workflow_deployment(
    session: Session,
    workflow_id: str,
    version_num: int,
    deployment_in: WorkflowDeploymentCreate,
    created_by: str,
) -> WorkflowDeployment:
    """Deploy a workflow version on a specific platform.

    If the caller supplies ``external_id`` we trust it and store as-is.
    Otherwise, for engine ``AWSHealthOmics (us-east)`` the API server
    registers the workflow on AWS HealthOmics via a Lambda and stores the
    returned ARN. For other engines the caller must provide ``external_id``.
    """
    # Verify version exists and belongs to this workflow
    version = get_workflow_version_by_num(session, workflow_id, version_num)

    # Verify engine is a registered platform
    _validate_engine(session, deployment_in.engine)

    # Check for duplicate (version, engine)
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
                f"Version {version_num} is already deployed "
                f"on engine '{deployment_in.engine}'."
            ),
        )

    if deployment_in.external_id:
        external_id = deployment_in.external_id
    elif deployment_in.engine == "AWSHealthOmics (us-east)":
        external_id = _register_workflow_on_omics(
            session, version.workflow, version, deployment_in.engine,
        )
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"external_id is required for engine "
                f"'{deployment_in.engine}'."
            ),
        )

    deployment = WorkflowDeployment(
        workflow_version_id=version.id,
        engine=deployment_in.engine,
        external_id=external_id,
        created_by=created_by,
    )

    session.add(deployment)
    session.commit()
    session.refresh(deployment)
    return deployment


def get_workflow_deployments(
    session: Session,
    workflow_id: str,
    version_num: int,
    engine: str | None = None,
) -> list[WorkflowDeployment]:
    """List platform deployments for a workflow version."""
    version = get_workflow_version_by_num(session, workflow_id, version_num)
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
    version_num: int,
    deployment_id: str,
) -> None:
    """Remove a workflow platform deployment."""
    version = get_workflow_version_by_num(session, workflow_id, version_num)
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
                f"for version {version_num}."
            ),
        )
    session.delete(deployment)
    session.commit()
