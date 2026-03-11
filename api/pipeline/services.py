"""
Pipeline Service

CRUD operations for Pipeline, PipelineAttribute, and PipelineWorkflow entities.
"""
from uuid import UUID

from fastapi import HTTPException, status
from sqlmodel import Session, select, func

from api.workflow.models import Attribute, Workflow
from api.pipeline.models import (
    Pipeline,
    PipelineAttribute,
    PipelineCreate,
    PipelinePublic,
    PipelinesPublic,
    PipelineWorkflow,
    WorkflowSummary,
)


# ---------------------------------------------------------------------------
# Pipeline CRUD
# ---------------------------------------------------------------------------

def create_pipeline(
    session: Session,
    pipeline_in: PipelineCreate,
    created_by: str,
) -> Pipeline:
    """Create a pipeline with optional attributes and workflow links."""
    pipeline = Pipeline(
        name=pipeline_in.name,
        version=pipeline_in.version,
        created_by=created_by,
    )

    session.add(pipeline)
    session.flush()

    # Handle attributes
    if pipeline_in.attributes:
        seen: set[str] = set()
        keys = [attr.key for attr in pipeline_in.attributes]
        dups = [k for k in keys if k in seen or seen.add(k)]
        if dups:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    f"Duplicate keys ({', '.join(dups)}) are not allowed "
                    f"in pipeline attributes."
                ),
            )

        attrs = [
            PipelineAttribute(
                pipeline_id=pipeline.id, key=attr.key, value=attr.value
            )
            for attr in pipeline_in.attributes
        ]
        session.add_all(attrs)

    # Handle optional workflow links
    if pipeline_in.workflow_ids:
        for wf_id in pipeline_in.workflow_ids:
            wf = session.exec(
                select(Workflow).where(Workflow.id == wf_id)
            ).first()
            if not wf:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Workflow '{wf_id}' not found.",
                )
            pw = PipelineWorkflow(
                pipeline_id=pipeline.id,
                workflow_id=wf.id,
                created_by=created_by,
            )
            session.add(pw)

    session.commit()
    session.refresh(pipeline)
    return pipeline


def get_pipelines(
    session: Session,
    page: int = 1,
    per_page: int = 20,
    sort_by: str = "name",
    sort_order: str = "asc",
) -> PipelinesPublic:
    """Paginated list of pipelines with sorting."""
    valid_sort_fields = {
        "id": Pipeline.id,
        "name": Pipeline.name,
        "created_at": Pipeline.created_at,
    }
    if sort_by not in valid_sort_fields:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Invalid sort_by field '{sort_by}'. "
                f"Valid fields are: {', '.join(valid_sort_fields.keys())}."
            ),
        )

    sort_column = valid_sort_fields[sort_by]
    if sort_order == "desc":
        sort_column = sort_column.desc()

    total_count = session.exec(
        select(func.count()).select_from(Pipeline)
    ).one()
    total_pages = (
        (total_count + per_page - 1) // per_page if total_count > 0 else 0
    )

    pipelines = session.exec(
        select(Pipeline)
        .order_by(sort_column)
        .offset((page - 1) * per_page)
        .limit(per_page)
    ).all()

    public = [pipeline_to_public(session, p) for p in pipelines]

    return PipelinesPublic(
        data=public,
        total_items=total_count,
        total_pages=total_pages,
        current_page=page,
        per_page=per_page,
        has_next=page < total_pages,
        has_prev=page > 1,
    )


def get_pipeline_by_id(session: Session, pipeline_id: str) -> Pipeline:
    """Fetch a single pipeline or 404."""
    pipeline = session.exec(
        select(Pipeline).where(Pipeline.id == UUID(pipeline_id))
    ).first()
    if not pipeline:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Pipeline with id '{pipeline_id}' not found.",
        )
    return pipeline


# ---------------------------------------------------------------------------
# Pipeline ↔ Workflow association
# ---------------------------------------------------------------------------

def add_workflow_to_pipeline(
    session: Session,
    pipeline_id: str,
    workflow_id: str,
    created_by: str,
) -> PipelineWorkflow:
    """Associate a workflow with a pipeline."""
    pipeline = get_pipeline_by_id(session, pipeline_id)

    wf = session.exec(
        select(Workflow).where(Workflow.id == UUID(workflow_id))
    ).first()
    if not wf:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Workflow '{workflow_id}' not found.",
        )

    # Check for duplicate
    existing = session.exec(
        select(PipelineWorkflow).where(
            PipelineWorkflow.pipeline_id == pipeline.id,
            PipelineWorkflow.workflow_id == wf.id,
        )
    ).first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"Workflow '{workflow_id}' is already associated "
                f"with pipeline '{pipeline_id}'."
            ),
        )

    pw = PipelineWorkflow(
        pipeline_id=pipeline.id,
        workflow_id=wf.id,
        created_by=created_by,
    )
    session.add(pw)
    session.commit()
    session.refresh(pw)
    return pw


def remove_workflow_from_pipeline(
    session: Session,
    pipeline_id: str,
    workflow_id: str,
) -> None:
    """Remove a workflow association from a pipeline."""
    pipeline = get_pipeline_by_id(session, pipeline_id)

    pw = session.exec(
        select(PipelineWorkflow).where(
            PipelineWorkflow.pipeline_id == pipeline.id,
            PipelineWorkflow.workflow_id == UUID(workflow_id),
        )
    ).first()
    if not pw:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=(
                f"Workflow '{workflow_id}' is not associated "
                f"with pipeline '{pipeline_id}'."
            ),
        )
    session.delete(pw)
    session.commit()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def pipeline_to_public(session: Session, pipeline: Pipeline) -> PipelinePublic:
    """Convert a Pipeline ORM object to its public representation."""
    attributes = None
    if pipeline.attributes:
        attributes = [
            Attribute(key=a.key, value=a.value)
            for a in pipeline.attributes
        ]

    # Fetch associated workflows via junction table
    workflows = None
    if pipeline.pipeline_workflows:
        wf_ids = [
            pw.workflow_id for pw in pipeline.pipeline_workflows
        ]
        wf_rows = session.exec(
            select(Workflow).where(Workflow.id.in_(wf_ids))
        ).all()
        workflows = [
            WorkflowSummary(id=wf.id, name=wf.name, version=wf.version)
            for wf in wf_rows
        ]

    return PipelinePublic(
        id=pipeline.id,
        name=pipeline.name,
        version=pipeline.version,
        created_at=pipeline.created_at,
        created_by=pipeline.created_by,
        attributes=attributes,
        workflows=workflows,
    )
