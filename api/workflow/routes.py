"""
Routes/endpoints for the Workflows API

Covers Workflow CRUD, WorkflowVersion, WorkflowVersionAlias,
and WorkflowDeployment endpoints.
"""

from typing import List, Literal
from fastapi import APIRouter, Query, status
from core.deps import SessionDep
from api.auth.deps import CurrentUser

from api.workflow.models import (
    WorkflowCreate,
    WorkflowPublic,
    WorkflowVersionCreate,
    WorkflowVersionPublic,
    WorkflowVersionAliasPublic,
    WorkflowVersionAliasSet,
    WorkflowDeploymentCreate,
    WorkflowDeploymentPublic,
)

from api.workflow import services

router = APIRouter(
    prefix="/workflows", tags=["Workflow Endpoints"],
)


# ---------------------------------------------------------------------------
# Workflow CRUD
# ---------------------------------------------------------------------------

@router.post(
    "",
    response_model=WorkflowPublic,
    tags=["Workflow Endpoints"],
    status_code=status.HTTP_201_CREATED,
)
def create_workflow(
    session: SessionDep,
    user: CurrentUser,
    workflow_in: WorkflowCreate,
) -> WorkflowPublic:
    """Create a new workflow identity with optional attributes."""
    workflow = services.create_workflow(
        session=session,
        workflow_in=workflow_in,
        created_by=user.username,
    )
    return services.workflow_to_public(workflow)


@router.get(
    "",
    response_model=List[WorkflowPublic],
    tags=["Workflow Endpoints"],
)
def get_workflows(
    session: SessionDep,
    page: int = Query(
        1, description="Page number (1-indexed)",
    ),
    per_page: int = Query(
        20, description="Number of items per page",
    ),
    sort_by: str = Query(
        "name", description="Field to sort by",
    ),
    sort_order: Literal["asc", "desc"] = Query(
        "asc", description="Sort order (asc or desc)",
    ),
) -> List[WorkflowPublic]:
    """Returns a paginated list of workflows."""
    workflows = services.get_workflows(
        session=session,
        page=page,
        per_page=per_page,
        sort_by=sort_by,
        sort_order=sort_order,
    )
    return [services.workflow_to_public(w) for w in workflows]


@router.get(
    "/{workflow_id}",
    response_model=WorkflowPublic,
    tags=["Workflow Endpoints"],
)
def get_workflow_by_id(
    session: SessionDep, workflow_id: str,
) -> WorkflowPublic:
    """Returns a single workflow by its ID."""
    workflow = services.get_workflow_by_id(
        session=session, workflow_id=workflow_id,
    )
    return services.workflow_to_public(workflow)


# ---------------------------------------------------------------------------
# WorkflowVersion
# ---------------------------------------------------------------------------

@router.post(
    "/{workflow_id}/versions",
    response_model=WorkflowVersionPublic,
    tags=["Workflow Endpoints"],
    status_code=status.HTTP_201_CREATED,
)
def create_workflow_version(
    session: SessionDep,
    user: CurrentUser,
    workflow_id: str,
    version_in: WorkflowVersionCreate,
) -> WorkflowVersionPublic:
    """Create a new version for a workflow."""
    version = services.create_workflow_version(
        session=session,
        workflow_id=workflow_id,
        version_in=version_in,
        created_by=user.username,
    )
    return services.workflow_version_to_public(version)


@router.get(
    "/{workflow_id}/versions",
    response_model=List[WorkflowVersionPublic],
    tags=["Workflow Endpoints"],
)
def get_workflow_versions(
    session: SessionDep, workflow_id: str,
) -> List[WorkflowVersionPublic]:
    """List all versions of a workflow."""
    versions = services.get_workflow_versions(
        session=session, workflow_id=workflow_id,
    )
    return [
        services.workflow_version_to_public(v)
        for v in versions
    ]


@router.get(
    "/{workflow_id}/versions/{version_id}",
    response_model=WorkflowVersionPublic,
    tags=["Workflow Endpoints"],
)
def get_workflow_version_by_id(
    session: SessionDep,
    workflow_id: str,
    version_id: str,
) -> WorkflowVersionPublic:
    """Get a specific workflow version."""
    # Verify workflow exists first
    services.get_workflow_by_id(session, workflow_id)
    version = services.get_workflow_version_by_id(
        session=session, version_id=version_id,
    )
    return services.workflow_version_to_public(version)


# ---------------------------------------------------------------------------
# WorkflowVersionAlias
# ---------------------------------------------------------------------------

@router.put(
    "/{workflow_id}/aliases/{alias}",
    response_model=WorkflowVersionAliasPublic,
    tags=["Workflow Endpoints"],
)
def set_workflow_version_alias(
    session: SessionDep,
    user: CurrentUser,
    workflow_id: str,
    alias: str,
    alias_in: WorkflowVersionAliasSet,
) -> WorkflowVersionAliasPublic:
    """Set or update an alias to point to a workflow version."""
    alias_record = services.set_workflow_version_alias(
        session=session,
        workflow_id=workflow_id,
        alias=alias,
        alias_in=alias_in,
        created_by=user.username,
    )
    return services.alias_to_public(alias_record)


@router.get(
    "/{workflow_id}/aliases",
    response_model=List[WorkflowVersionAliasPublic],
    tags=["Workflow Endpoints"],
)
def get_workflow_version_aliases(
    session: SessionDep,
    workflow_id: str,
    alias: str | None = Query(
        None, description="Filter to a specific alias",
    ),
) -> List[WorkflowVersionAliasPublic]:
    """List aliases for a workflow, optionally filtered by alias name."""
    aliases = services.get_workflow_version_aliases(
        session=session, workflow_id=workflow_id, alias=alias,
    )
    return [services.alias_to_public(a) for a in aliases]


@router.delete(
    "/{workflow_id}/aliases/{alias}",
    status_code=status.HTTP_204_NO_CONTENT,
    tags=["Workflow Endpoints"],
)
def delete_workflow_version_alias(
    session: SessionDep,
    workflow_id: str,
    alias: str,
) -> None:
    """Remove an alias from a workflow."""
    services.delete_workflow_version_alias(
        session=session,
        workflow_id=workflow_id,
        alias=alias,
    )


# ---------------------------------------------------------------------------
# WorkflowDeployment (workflow-level with filters)
# ---------------------------------------------------------------------------

@router.get(
    "/{workflow_id}/deployments",
    response_model=List[WorkflowDeploymentPublic],
    tags=["Workflow Endpoints"],
)
def get_workflow_deployments_for_workflow(
    session: SessionDep,
    workflow_id: str,
    alias: str | None = Query(
        None,
        description=(
            "Filter by alias (e.g. production). "
            "Resolves the alias to its version and returns "
            "deployments for that version only."
        ),
    ),
    engine: str | None = Query(
        None,
        description="Filter by engine/platform name",
    ),
) -> List[WorkflowDeploymentPublic]:
    """List deployments across all versions of a workflow.

    Optional query filters:
    - **alias**: resolve an alias to its version, return only
      that version's deployments
    - **engine**: restrict results to a specific platform

    Combine both to get a single deployment in one call, e.g.
    ``?alias=production&engine=Arvados``.
    """
    deps = services.get_workflow_deployments_for_workflow(
        session=session,
        workflow_id=workflow_id,
        alias=alias,
        engine=engine,
    )
    return [
        WorkflowDeploymentPublic(
            id=r.id,
            workflow_version_id=r.workflow_version_id,
            engine=r.engine,
            external_id=r.external_id,
            created_at=r.created_at,
            created_by=r.created_by,
        )
        for r in deps
    ]


# ---------------------------------------------------------------------------
# WorkflowDeployment (nested under version)
# ---------------------------------------------------------------------------

@router.post(
    "/{workflow_id}/versions/{version_id}/deployments",
    response_model=WorkflowDeploymentPublic,
    tags=["Workflow Endpoints"],
    status_code=status.HTTP_201_CREATED,
)
def create_workflow_deployment(
    session: SessionDep,
    user: CurrentUser,
    workflow_id: str,
    version_id: str,
    deployment_in: WorkflowDeploymentCreate,
) -> WorkflowDeploymentPublic:
    """Deploy a workflow version on a specific platform."""
    dep = services.create_workflow_deployment(
        session=session,
        workflow_id=workflow_id,
        version_id=version_id,
        deployment_in=deployment_in,
        created_by=user.username,
    )
    return WorkflowDeploymentPublic(
        id=dep.id,
        workflow_version_id=dep.workflow_version_id,
        engine=dep.engine,
        external_id=dep.external_id,
        created_at=dep.created_at,
        created_by=dep.created_by,
    )


@router.get(
    "/{workflow_id}/versions/{version_id}/deployments",
    response_model=List[WorkflowDeploymentPublic],
    tags=["Workflow Endpoints"],
)
def get_workflow_deployments(
    session: SessionDep,
    workflow_id: str,
    version_id: str,
    engine: str | None = Query(
        None,
        description="Filter by engine/platform name",
    ),
) -> List[WorkflowDeploymentPublic]:
    """List platform deployments for a workflow version."""
    deps = services.get_workflow_deployments(
        session=session,
        workflow_id=workflow_id,
        version_id=version_id,
        engine=engine,
    )
    return [
        WorkflowDeploymentPublic(
            id=r.id,
            workflow_version_id=r.workflow_version_id,
            engine=r.engine,
            external_id=r.external_id,
            created_at=r.created_at,
            created_by=r.created_by,
        )
        for r in deps
    ]


@router.delete(
    "/{workflow_id}/versions/{version_id}"
    "/deployments/{deployment_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    tags=["Workflow Endpoints"],
)
def delete_workflow_deployment(
    session: SessionDep,
    workflow_id: str,
    version_id: str,
    deployment_id: str,
) -> None:
    """Remove a platform deployment."""
    services.delete_workflow_deployment(
        session=session,
        workflow_id=workflow_id,
        version_id=version_id,
        deployment_id=deployment_id,
    )
