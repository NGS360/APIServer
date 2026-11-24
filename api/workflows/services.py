"""
Services for the Workflows API
"""

from uuid import UUID
from sqlmodel import Session, select
from api.workflows.models import (
    Workflow
)


def get_workflow_by_id(
    session: Session, workflow_id: str
) -> Workflow | None:
    ''' Return a single workflow by id UUID '''
    wf_uuid = UUID(workflow_id)
    workflow = session.exec(
        select(Workflow).where(Workflow.id == wf_uuid)
    ).first()
    return workflow
