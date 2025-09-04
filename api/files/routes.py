"""
Routes/endpoints for the Files API
"""

from typing import Literal
from fastapi import APIRouter, Query, status
from core.deps import SessionDep
from api.files.models import File, FileCreate, FilePublic, FilesPublic
import api.files.services as services

router = APIRouter(prefix="/files", tags=["File Endpoints"])


@router.post(
    "",
    response_model=FilePublic,
    tags=["File Endpoints"],
    status_code=status.HTTP_201_CREATED,
)
def create_file(session: SessionDep, file_in: FileCreate) -> File:
    """
    Create a new file with optional attributes.
    """
    return services.create_file(session=session, file_in=file_in)


@router.get("", response_model=FilesPublic, tags=["File Endpoints"])
def get_files(
    session: SessionDep,
    page: int = Query(1, description="Page number (1-indexed)"),
    per_page: int = Query(20, description="Number of items per page"),
    sort_by: str = Query("file_id", description="Field to sort by"),
    sort_order: Literal["asc", "desc"] = Query(
        "asc", description="Sort order (asc or desc)"
    ),
) -> FilesPublic:
    """
    Returns a paginated list of files.
    """
    return services.get_files(
        session=session,
        page=page,
        per_page=per_page,
        sort_by=sort_by,
        sort_order=sort_order,
    )


@router.get("/{file_id}", response_model=FilePublic, tags=["File Endpoints"])
def get_file_by_file_id(session: SessionDep, file_id: str) -> File:
    """
    Returns a single file by its file_id.
    Note: This is different from its internal "id".
    """
    return services.get_file_by_file_id(session=session, file_id=file_id)
