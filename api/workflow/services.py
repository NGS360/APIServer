"""
Workflow Service
"""
from fastapi import HTTPException, status
from sqlmodel import Session

from api.workflow.models import WorkflowCreate, Workflow, WorkflowAttribute


def create_workflow(session: Session, workflow_in: WorkflowCreate) -> Workflow:
    ''' Register a workflow with optional attributes '''
    # Create initial workflow
    workflow = Workflow(workflow_in.model_dump())

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
