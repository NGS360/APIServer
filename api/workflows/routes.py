"""
Routes/endpoints for the Workflows API
"""

from fastapi import (
    APIRouter, Depends, HTTPException, status
)
from core.deps import SessionDep

from api.rbac.deps import (
    require_permission
)
from api.rbac.permissions import Permission
from api.workflows import services
from api.workflows.models import (
    Workflow
)
router = APIRouter(prefix="/workflows")


@router.get(
    "/{workflow_id}",
    response_model=Workflow,
    tags=["Workflow Endpoints"],
    dependencies=[Depends(require_permission(Permission.WORKFLOW_READ))],
)
def get_workflow_by_id(
    session: SessionDep, workflow_id: str,
) -> Workflow:
    """Returns a single workflow by its ID."""
    workflow = services.get_workflow_by_id(
        session=session, workflow_id=workflow_id,
    )
    if not workflow:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Workflow {workflow_id} not found.",
        )
    return workflow
