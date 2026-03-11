"""
Routes/endpoints for the Pipelines API

Covers Pipeline CRUD and Pipeline ↔ Workflow association.
"""

import uuid
from typing import Literal
from fastapi import APIRouter, Query, status
from core.deps import SessionDep
from api.auth.deps import CurrentUser

from api.pipeline.models import (
    PipelineCreate,
    PipelinePublic,
    PipelinesPublic,
)
from api.pipeline import services

router = APIRouter(prefix="/pipelines", tags=["Pipeline Endpoints"])


# ---------------------------------------------------------------------------
# Pipeline CRUD
# ---------------------------------------------------------------------------

@router.post(
    "",
    response_model=PipelinePublic,
    tags=["Pipeline Endpoints"],
    status_code=status.HTTP_201_CREATED,
)
def create_pipeline(
    session: SessionDep,
    user: CurrentUser,
    pipeline_in: PipelineCreate,
) -> PipelinePublic:
    """Create a pipeline with optional attributes and workflow links."""
    pipeline = services.create_pipeline(
        session=session,
        pipeline_in=pipeline_in,
        created_by=user.username,
    )
    return services.pipeline_to_public(session, pipeline)


@router.get(
    "",
    response_model=PipelinesPublic,
    tags=["Pipeline Endpoints"],
)
def get_pipelines(
    session: SessionDep,
    page: int = Query(1, description="Page number (1-indexed)"),
    per_page: int = Query(20, description="Number of items per page"),
    sort_by: str = Query("name", description="Field to sort by"),
    sort_order: Literal["asc", "desc"] = Query(
        "asc", description="Sort order (asc or desc)"
    ),
) -> PipelinesPublic:
    """Returns a paginated list of pipelines."""
    return services.get_pipelines(
        session=session,
        page=page,
        per_page=per_page,
        sort_by=sort_by,
        sort_order=sort_order,
    )


@router.get(
    "/{pipeline_id}",
    response_model=PipelinePublic,
    tags=["Pipeline Endpoints"],
)
def get_pipeline_by_id(
    session: SessionDep, pipeline_id: str
) -> PipelinePublic:
    """Returns a single pipeline by its ID."""
    pipeline = services.get_pipeline_by_id(
        session=session, pipeline_id=pipeline_id
    )
    return services.pipeline_to_public(session, pipeline)


# ---------------------------------------------------------------------------
# Pipeline ↔ Workflow association
# ---------------------------------------------------------------------------

@router.post(
    "/{pipeline_id}/workflows",
    status_code=status.HTTP_201_CREATED,
    tags=["Pipeline Endpoints"],
)
def add_workflow_to_pipeline(
    session: SessionDep,
    user: CurrentUser,
    pipeline_id: str,
    workflow_id: uuid.UUID = Query(
        ..., description="UUID of the workflow to associate"
    ),
) -> dict:
    """Add a workflow to a pipeline."""
    pw = services.add_workflow_to_pipeline(
        session=session,
        pipeline_id=pipeline_id,
        workflow_id=str(workflow_id),
        created_by=user.username,
    )
    return {"id": str(pw.id), "message": "Workflow added to pipeline."}


@router.delete(
    "/{pipeline_id}/workflows/{workflow_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    tags=["Pipeline Endpoints"],
)
def remove_workflow_from_pipeline(
    session: SessionDep,
    pipeline_id: str,
    workflow_id: str,
) -> None:
    """Remove a workflow from a pipeline."""
    services.remove_workflow_from_pipeline(
        session=session,
        pipeline_id=pipeline_id,
        workflow_id=workflow_id,
    )
