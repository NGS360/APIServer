"""
Routes/endpoints for the Workflows API

Covers Workflow CRUD and WorkflowRun endpoints.
"""

from typing import List, Literal
from fastapi import APIRouter, Query, status
from core.deps import SessionDep
from api.auth.deps import CurrentUser

from api.workflow.models import (
    WorkflowCreate,
    WorkflowPublic,
    WorkflowRunCreate,
    WorkflowRunPublic,
    WorkflowRunsPublic,
)

from api.workflow import services

router = APIRouter(prefix="/workflows", tags=["Workflow Endpoints"])


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
    """Create a new workflow with optional attributes."""
    workflow = services.create_workflow(
        session=session, workflow_in=workflow_in, created_by=user.username
    )
    return services.workflow_to_public(workflow)


@router.get(
    "",
    response_model=List[WorkflowPublic],
    tags=["Workflow Endpoints"],
)
def get_workflows(
    session: SessionDep,
    page: int = Query(1, description="Page number (1-indexed)"),
    per_page: int = Query(20, description="Number of items per page"),
    sort_by: str = Query("name", description="Field to sort by"),
    sort_order: Literal["asc", "desc"] = Query(
        "asc", description="Sort order (asc or desc)"
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
    session: SessionDep, workflow_id: str
) -> WorkflowPublic:
    """Returns a single workflow by its ID."""
    workflow = services.get_workflow_by_id(
        session=session, workflow_id=workflow_id
    )
    return services.workflow_to_public(workflow)


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
    page: int = Query(1, description="Page number (1-indexed)"),
    per_page: int = Query(20, description="Number of items per page"),
    sort_by: str = Query(
        "created_at", description="Field to sort by"
    ),
    sort_order: Literal["asc", "desc"] = Query(
        "desc", description="Sort order"
    ),
) -> WorkflowRunsPublic:
    """List runs for a workflow (paginated)."""
    return services.get_workflow_runs(
        session=session,
        workflow_id=workflow_id,
        page=page,
        per_page=per_page,
        sort_by=sort_by,
        sort_order=sort_order,
    )


# Separate top-level path for single run lookup/update (not nested under workflow)
run_router = APIRouter(
    prefix="/workflow-runs", tags=["Workflow Endpoints"]
)


@run_router.get(
    "/{run_id}",
    response_model=WorkflowRunPublic,
    tags=["Workflow Endpoints"],
)
def get_workflow_run_by_id(
    session: SessionDep, run_id: str
) -> WorkflowRunPublic:
    """Get a single workflow run by its ID."""
    run = services.get_workflow_run_by_id(session=session, run_id=run_id)
    return services.workflow_run_to_public(run)
