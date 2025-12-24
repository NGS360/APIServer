"""
Workflow Service
"""
from uuid import UUID
from fastapi import HTTPException, status
from sqlmodel import Session, select

from api.workflow.models import WorkflowCreate, Workflow, WorkflowAttribute


def create_workflow(session: Session, workflow_in: WorkflowCreate) -> Workflow:
    ''' Register a workflow with optional attributes '''
    # Create initial workflow
    workflow = Workflow(
        name=workflow_in.name,
        definition_uri=workflow_in.definition_uri,
        engine=workflow_in.engine,
    )

    session.add(workflow)
    session.flush()

    # Handle attribute mapping
    if workflow_in.attributes:
        # Prevent duplicate keys
        seen = set()
        keys = [attr.key for attr in workflow_in.attributes]
        dups = [k for k in keys if k in seen or seen.add(k)]
        if dups:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Duplicate keys ({', '.join(dups)}) are not allowed in workflow attributes.",
            )

        # Parse and create workflow attributes
        # linking to new workflow
        workflow_attributes = [
            WorkflowAttribute(workflow_id=workflow.id, key=attr.key, value=attr.value)
            for attr in workflow_in.attributes
        ]

        # Update database with attribute links
        session.add_all(workflow_attributes)

    # With orm_mode=True, attributes will be eagerly loaded
    # and mapped to ProjectPublic via response model
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
    ''' Returns a paginated list of workflows '''
    valid_sort_fields = {"workflow_id": Workflow.id, "name": Workflow.name}
    if sort_by not in valid_sort_fields:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid sort_by field '{sort_by}'. "
                   f"Valid fields are: {', '.join(valid_sort_fields.keys())}.",
        )

    sort_column = valid_sort_fields[sort_by]
    if sort_order == "desc":
        sort_column = sort_column.desc()

    offset = (page - 1) * per_page

    workflows = session.query(Workflow).order_by(sort_column).offset(offset).limit(per_page).all()
    return workflows


def get_workflow_by_workflow_id(session: Session, workflow_id: str) -> Workflow:
    ''' Returns a single workflow by its workflow_id '''
    workflow = session.exec(
        select(Workflow).where(Workflow.id == UUID(workflow_id))
    ).first()
    if not workflow:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Workflow with workflow_id '{workflow_id}' not found.",
        )
    return workflow
