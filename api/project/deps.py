"""
Project dependencies for dependency injection
"""

from typing import Annotated
from fastapi import Depends, HTTPException, status
from sqlmodel import select

from core.deps import SessionDep
from api.project.models import Project


def get_validated_project(
    project_id: str,
    session: SessionDep
) -> Project:
    """
    Dependency that validates a project exists and returns the database object.

    Args:
        project_id: The project ID from the path parameter
        session: Database session

    Returns:
        Project database object

    Raises:
        HTTPException: 404 if project not found
    """
    project = session.exec(
        select(Project).where(Project.project_id == project_id)
    ).first()

    if not project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Project {project_id} not found."
        )

    return project


# Type alias for clean usage in route signatures
ProjectDep = Annotated[Project, Depends(get_validated_project)]
