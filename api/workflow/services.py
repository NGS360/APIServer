"""
Workflow Service

CRUD operations for Workflow, WorkflowRegistration, and WorkflowRun entities.
"""
from uuid import UUID

from fastapi import HTTPException, status
from sqlmodel import Session, select, func

from api.platforms.models import Platform
from api.workflow.models import (
    Attribute,
    Workflow,
    WorkflowAttribute,
    WorkflowCreate,
    WorkflowPublic,
    WorkflowRegistration,
    WorkflowRegistrationCreate,
    WorkflowRegistrationPublic,
    WorkflowRun,
    WorkflowRunAttribute,
    WorkflowRunCreate,
    WorkflowRunPublic,
    WorkflowRunsPublic,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _validate_engine(session: Session, engine: str) -> None:
    """Verify that ``engine`` matches a registered Platform name."""
    if not session.get(Platform, engine):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Engine '{engine}' is not a registered platform. "
                "Create it via POST /platforms first."
            ),
        )


# ---------------------------------------------------------------------------
# Workflow CRUD
# ---------------------------------------------------------------------------

def create_workflow(session: Session, workflow_in: WorkflowCreate, created_by: str) -> Workflow:
    """Register a workflow with optional attributes."""
    workflow = Workflow(
        name=workflow_in.name,
        version=workflow_in.version,
        definition_uri=workflow_in.definition_uri,
        created_by=created_by,
    )

    session.add(workflow)
    session.flush()

    # Handle attribute mapping
    if workflow_in.attributes:
        # Prevent duplicate keys
        seen: set[str] = set()
        keys = [attr.key for attr in workflow_in.attributes]
        dups = [k for k in keys if k in seen or seen.add(k)]
        if dups:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Duplicate keys ({', '.join(dups)}) are not allowed in workflow attributes.",
            )

        workflow_attributes = [
            WorkflowAttribute(workflow_id=workflow.id, key=attr.key, value=attr.value)
            for attr in workflow_in.attributes
        ]
        session.add_all(workflow_attributes)

    session.commit()
    session.refresh(workflow)
    return workflow


def get_workflows(
    session: Session,
    page: int = 1,
    per_page: int = 20,
    sort_by: str = "name",
    sort_order: str = "asc",
) -> dict:
    """Returns a paginated list of workflows."""
    valid_sort_fields = {"id": Workflow.id, "name": Workflow.name, "created_at": Workflow.created_at}
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


def get_workflow_by_id(session: Session, workflow_id: str) -> Workflow:
    """Returns a single workflow by its UUID."""
    workflow = session.exec(
        select(Workflow).where(Workflow.id == UUID(workflow_id))
    ).first()
    if not workflow:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Workflow with id '{workflow_id}' not found.",
        )
    return workflow


def workflow_to_public(workflow: Workflow) -> WorkflowPublic:
    """Convert a Workflow ORM object to its public representation."""
    registrations = None
    if workflow.registrations:
        registrations = [
            WorkflowRegistrationPublic(
                id=r.id,
                workflow_id=r.workflow_id,
                engine=r.engine,
                external_id=r.external_id,
                created_at=r.created_at,
                created_by=r.created_by,
            )
            for r in workflow.registrations
        ]

    attributes = None
    if workflow.attributes:
        attributes = [
            Attribute(key=a.key, value=a.value) for a in workflow.attributes
        ]

    return WorkflowPublic(
        id=workflow.id,
        name=workflow.name,
        version=workflow.version,
        definition_uri=workflow.definition_uri,
        created_at=workflow.created_at,
        created_by=workflow.created_by,
        attributes=attributes,
        registrations=registrations,
    )


# ---------------------------------------------------------------------------
# WorkflowRegistration CRUD
# ---------------------------------------------------------------------------

def create_workflow_registration(
    session: Session,
    workflow_id: str,
    registration_in: WorkflowRegistrationCreate,
    created_by: str,
) -> WorkflowRegistration:
    """Register a workflow on a specific platform."""
    # Verify workflow exists
    workflow = get_workflow_by_id(session, workflow_id)

    # Verify engine is a registered platform
    _validate_engine(session, registration_in.engine)

    # Check for duplicate (workflow_id, engine) combo
    existing = session.exec(
        select(WorkflowRegistration).where(
            WorkflowRegistration.workflow_id == workflow.id,
            WorkflowRegistration.engine == registration_in.engine,
        )
    ).first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"Workflow '{workflow_id}' is already registered "
                f"on engine '{registration_in.engine}'."
            ),
        )

    registration = WorkflowRegistration(
        workflow_id=workflow.id,
        engine=registration_in.engine,
        external_id=registration_in.external_id,
        created_by=created_by,
    )

    session.add(registration)
    session.commit()
    session.refresh(registration)
    return registration


def get_workflow_registrations(session: Session, workflow_id: str) -> list[WorkflowRegistration]:
    """List all platform registrations for a workflow."""
    workflow = get_workflow_by_id(session, workflow_id)
    registrations = session.exec(
        select(WorkflowRegistration).where(WorkflowRegistration.workflow_id == workflow.id)
    ).all()
    return registrations


def delete_workflow_registration(session: Session, workflow_id: str, registration_id: str) -> None:
    """Remove a workflow platform registration."""
    workflow = get_workflow_by_id(session, workflow_id)
    registration = session.exec(
        select(WorkflowRegistration).where(
            WorkflowRegistration.id == UUID(registration_id),
            WorkflowRegistration.workflow_id == workflow.id,
        )
    ).first()
    if not registration:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Registration '{registration_id}' not found for workflow '{workflow_id}'.",
        )
    session.delete(registration)
    session.commit()


# ---------------------------------------------------------------------------
# WorkflowRun CRUD
# ---------------------------------------------------------------------------

def create_workflow_run(
    session: Session,
    workflow_id: str,
    run_in: WorkflowRunCreate,
    created_by: str,
) -> WorkflowRun:
    """Create a workflow provenance record."""
    workflow = get_workflow_by_id(session, workflow_id)

    # Verify engine is a registered platform
    _validate_engine(session, run_in.engine)

    workflow_run = WorkflowRun(
        workflow_id=workflow.id,
        engine=run_in.engine,
        external_run_id=run_in.external_run_id,
        created_by=created_by,
    )

    session.add(workflow_run)
    session.flush()

    # Handle run attributes
    if run_in.attributes:
        run_attributes = [
            WorkflowRunAttribute(workflow_run_id=workflow_run.id, key=attr.key, value=attr.value)
            for attr in run_in.attributes
        ]
        session.add_all(run_attributes)

    session.commit()
    session.refresh(workflow_run)
    return workflow_run


def get_workflow_runs(
    session: Session,
    workflow_id: str,
    page: int = 1,
    per_page: int = 20,
    sort_by: str = "created_at",
    sort_order: str = "desc",
) -> WorkflowRunsPublic:
    """Paginated list of runs for a workflow."""
    workflow = get_workflow_by_id(session, workflow_id)

    valid_sort_fields = {
        "created_at": WorkflowRun.created_at,
    }
    if sort_by not in valid_sort_fields:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid sort_by field '{sort_by}'. "
                   f"Valid fields are: {', '.join(valid_sort_fields.keys())}.",
        )

    sort_column = valid_sort_fields[sort_by]
    if sort_order == "desc":
        sort_column = sort_column.desc()

    total_count = session.exec(
        select(func.count()).select_from(WorkflowRun).where(WorkflowRun.workflow_id == workflow.id)
    ).one()
    total_pages = (total_count + per_page - 1) // per_page if total_count > 0 else 0

    runs = session.exec(
        select(WorkflowRun)
        .where(WorkflowRun.workflow_id == workflow.id)
        .order_by(sort_column)
        .offset((page - 1) * per_page)
        .limit(per_page)
    ).all()

    public_runs = [workflow_run_to_public(r) for r in runs]

    return WorkflowRunsPublic(
        data=public_runs,
        total_items=total_count,
        total_pages=total_pages,
        current_page=page,
        per_page=per_page,
        has_next=page < total_pages,
        has_prev=page > 1,
    )


def get_workflow_run_by_id(session: Session, run_id: str) -> WorkflowRun:
    """Get a single workflow run by its UUID."""
    workflow_run = session.exec(
        select(WorkflowRun).where(WorkflowRun.id == UUID(run_id))
    ).first()
    if not workflow_run:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Workflow run with id '{run_id}' not found.",
        )
    return workflow_run


def workflow_run_to_public(run: WorkflowRun) -> WorkflowRunPublic:
    """Convert a WorkflowRun ORM object to its public representation."""
    attributes = None
    if run.attributes:
        attributes = [Attribute(key=a.key, value=a.value) for a in run.attributes]

    workflow_name = run.workflow.name if run.workflow else None

    return WorkflowRunPublic(
        id=run.id,
        workflow_id=run.workflow_id,
        workflow_name=workflow_name,
        engine=run.engine,
        external_run_id=run.external_run_id,
        created_at=run.created_at,
        created_by=run.created_by,
        attributes=attributes,
    )
