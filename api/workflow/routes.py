"""
Routes/endpoints for the Workflows API

Covers Workflow CRUD, WorkflowVersion, WorkflowVersionAlias,
WorkflowRegistration, and WorkflowRun endpoints.
"""

from typing import List, Literal
from fastapi import APIRouter, Query, status
from core.deps import SessionDep
from api.auth.deps import CurrentUser

from api.workflow.models import (
    VersionAlias,
    WorkflowCreate,
    WorkflowPublic,
    WorkflowVersionCreate,
    WorkflowVersionPublic,
    WorkflowVersionAliasPublic,
    WorkflowVersionAliasSet,
    WorkflowRegistrationCreate,
    WorkflowRegistrationPublic,
    WorkflowRunCreate,
    WorkflowRunPublic,
    WorkflowRunsPublic,
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
    alias: VersionAlias,
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
    session: SessionDep, workflow_id: str,
) -> List[WorkflowVersionAliasPublic]:
    """List all aliases for a workflow."""
    aliases = services.get_workflow_version_aliases(
        session=session, workflow_id=workflow_id,
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
    alias: VersionAlias,
) -> None:
    """Remove an alias from a workflow."""
    services.delete_workflow_version_alias(
        session=session,
        workflow_id=workflow_id,
        alias=alias,
    )


# ---------------------------------------------------------------------------
# WorkflowRegistration (nested under version)
# ---------------------------------------------------------------------------

@router.post(
    "/{workflow_id}/versions/{version_id}/registrations",
    response_model=WorkflowRegistrationPublic,
    tags=["Workflow Endpoints"],
    status_code=status.HTTP_201_CREATED,
)
def create_workflow_registration(
    session: SessionDep,
    user: CurrentUser,
    workflow_id: str,
    version_id: str,
    registration_in: WorkflowRegistrationCreate,
) -> WorkflowRegistrationPublic:
    """Register a workflow version on a specific platform."""
    reg = services.create_workflow_registration(
        session=session,
        workflow_id=workflow_id,
        version_id=version_id,
        registration_in=registration_in,
        created_by=user.username,
    )
    return WorkflowRegistrationPublic(
        id=reg.id,
        workflow_version_id=reg.workflow_version_id,
        engine=reg.engine,
        external_id=reg.external_id,
        created_at=reg.created_at,
        created_by=reg.created_by,
    )


@router.get(
    "/{workflow_id}/versions/{version_id}/registrations",
    response_model=List[WorkflowRegistrationPublic],
    tags=["Workflow Endpoints"],
)
def get_workflow_registrations(
    session: SessionDep,
    workflow_id: str,
    version_id: str,
) -> List[WorkflowRegistrationPublic]:
    """List platform registrations for a workflow version."""
    regs = services.get_workflow_registrations(
        session=session,
        workflow_id=workflow_id,
        version_id=version_id,
    )
    return [
        WorkflowRegistrationPublic(
            id=r.id,
            workflow_version_id=r.workflow_version_id,
            engine=r.engine,
            external_id=r.external_id,
            created_at=r.created_at,
            created_by=r.created_by,
        )
        for r in regs
    ]


@router.delete(
    "/{workflow_id}/versions/{version_id}"
    "/registrations/{registration_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    tags=["Workflow Endpoints"],
)
def delete_workflow_registration(
    session: SessionDep,
    workflow_id: str,
    version_id: str,
    registration_id: str,
) -> None:
    """Remove a platform registration."""
    services.delete_workflow_registration(
        session=session,
        workflow_id=workflow_id,
        version_id=version_id,
        registration_id=registration_id,
    )


# ---------------------------------------------------------------------------
# WorkflowRun
# ---------------------------------------------------------------------------

@router.post(
    "/{workflow_id}/runs",
    response_model=WorkflowRunPublic,
    tags=["Workflow Endpoints"],
    status_code=status.HTTP_201_CREATED,
)
def create_workflow_run(
    session: SessionDep,
    user: CurrentUser,
    workflow_id: str,
    run_in: WorkflowRunCreate,
) -> WorkflowRunPublic:
    """Create a workflow execution record."""
    run = services.create_workflow_run(
        session=session,
        workflow_id=workflow_id,
        run_in=run_in,
        created_by=user.username,
    )
    return services.workflow_run_to_public(run)


@router.get(
    "/{workflow_id}/runs",
    response_model=WorkflowRunsPublic,
    tags=["Workflow Endpoints"],
)
def get_workflow_runs(
    session: SessionDep,
    workflow_id: str,
    page: int = Query(
        1, description="Page number (1-indexed)",
    ),
    per_page: int = Query(
        20, description="Number of items per page",
    ),
    sort_by: str = Query(
        "created_at", description="Field to sort by",
    ),
    sort_order: Literal["asc", "desc"] = Query(
        "desc", description="Sort order",
    ),
) -> WorkflowRunsPublic:
    """List runs for a workflow (paginated, across all versions)."""
    return services.get_workflow_runs(
        session=session,
        workflow_id=workflow_id,
        page=page,
        per_page=per_page,
        sort_by=sort_by,
        sort_order=sort_order,
    )


# Separate top-level path for single run lookup
run_router = APIRouter(
    prefix="/workflow-runs", tags=["Workflow Endpoints"],
)


@run_router.get(
    "/{run_id}",
    response_model=WorkflowRunPublic,
    tags=["Workflow Endpoints"],
)
def get_workflow_run_by_id(
    session: SessionDep, run_id: str,
) -> WorkflowRunPublic:
    """Get a single workflow run by its ID."""
    run = services.get_workflow_run_by_id(
        session=session, run_id=run_id,
    )
    return services.workflow_run_to_public(run)
