"""
Workflow Service
"""
import json
import logging
import os
from uuid import UUID
from fastapi import HTTPException, status
from sqlmodel import Session, select
import boto3

from api.workflow.models import WorkflowCreate, Workflow, WorkflowAttribute
from core.config import get_settings

logger = logging.getLogger(__name__)


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

    # Call Lambda function to register workflow if engine is Omics
    if workflow.engine == "AWSHealthOmics":
        try:
            omics_workflow_id = _register_workflow_with_omics(workflow)
            if omics_workflow_id:
                # Update workflow with AWS Omics workflow ID
                workflow.engine_id = omics_workflow_id
                session.add(workflow)
                session.commit()
                session.refresh(workflow)
                logger.info(f"Successfully registered workflow {workflow.id} in AWS Omics with ID: {omics_workflow_id}")
        except Exception as e:
            # Log error but don't fail workflow creation
            logger.error(f"Failed to register workflow {workflow.id} in AWS Omics: {str(e)}")

    return workflow


def _register_workflow_with_omics(workflow: Workflow) -> str | None:
    """
    Register workflow with AWS Omics via Lambda function.

    Args:
        workflow: The workflow to register

    Returns:
        AWS Omics workflow ID if successful, None if failed
    """
    # Prepare payload for Lambda function
    lambda_payload = {
        "source": "ngs360",
        "action": "register_workflow",
        "cwl_s3_path": workflow.definition_uri,
        "name": workflow.name,
        "id": workflow.id
    }

    try:
        # Create Lambda client
        lambda_client = boto3.client("lambda", region_name=get_settings().AWS_REGION)

        # Invoke Lambda function synchronously
        omics_lambda_name = os.getenv('OMICS_LAMBDA')
        response = lambda_client.invoke(
            FunctionName=omics_lambda_name,
            InvocationType="RequestResponse",
            Payload=json.dumps(lambda_payload)
        )
        response_payload = json.loads(response["Payload"].read().decode('utf-8'))

        # Check if registration was successful
        if response_payload.get("statusCode") == 200:
            return response_payload.get("workflow_id")
        else:
            error_msg = response_payload.get("message", "Unknown error")
            logger.error(f"Lambda function failed to register workflow {workflow.id}: {error_msg}")
            return None
    except Exception as e:
        logger.error(f"Failed to register workflow {workflow.id} with AWS Omics: {str(e)}")
        return None


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

    workflows = session.exec(
        select(Workflow).order_by(sort_column).offset(offset).limit(per_page)
    ).all()
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
