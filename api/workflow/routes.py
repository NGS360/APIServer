"""
Routes/endpoints for the Workflows API
"""

from typing import List, Literal
from fastapi import APIRouter, Query, status
from core.deps import SessionDep

from api.workflow.models import WorkflowCreate, WorkflowPublic

from api.workflow import services

router = APIRouter(prefix="/workflows", tags=["Workflow Endpoints"])


@router.post(
    "",
    response_model=WorkflowPublic,
    tags=["Workflow Endpoints"],
    status_code=status.HTTP_201_CREATED,
)
def create_workflow(session: SessionDep, workflow_in: WorkflowCreate) -> WorkflowPublic:
    """
    Create a new workflow with optional attributes.
    """
    workflow = services.create_workflow(session=session, workflow_in=workflow_in)
    return WorkflowPublic.model_validate(workflow)


@router.get("", response_model=WorkflowPublic, tags=["Workflow Endpoints"])
def get_workflows(
    session: SessionDep,
    page: int = Query(1, description="Page number (1-indexed)"),
    per_page: int = Query(20, description="Number of items per page"),
    sort_by: str = Query("workflow_id", description="Field to sort by"),
    sort_order: Literal["asc", "desc"] = Query(
        "asc", description="Sort order (asc or desc)"
    ),
) -> List[WorkflowPublic]:
    """
    Returns a paginated list of workflows.
    """
    return services.get_workflows(
        session=session,
        page=page,
        per_page=per_page,
        sort_by=sort_by,
        sort_order=sort_order,
    )


@router.get(
    "/{workflow_id}", response_model=WorkflowPublic, tags=["Workflow Endpoints"]
)
def get_workflow_by_workflow_id(session: SessionDep, workflow_id: str) -> WorkflowPublic:
    """
    Returns a single workflow by its workflow_id.
    Note: This is different from its internal "id".
    """
    return services.get_workflow_by_workflow_id(
        session=session, workflow_id=workflow_id
    )
