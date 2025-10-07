"""
Routes/endpoints for the Files API
"""

from fastapi import APIRouter, Depends, Query

from api.files.models import FileBrowserData
import api.files.services as services
from core.deps import get_s3_client

router = APIRouter(prefix="/files", tags=["File Endpoints"])


@router.get("/list", response_model=FileBrowserData, tags=["File Endpoints"])
def list_files(
    uri: str = Query(
        ...,
        description="URI to list (e.g., s3://bucket/folder/ or /local/path)"
    ),
    storage_root: str = Query(
        ...,
        description=(
            "Root directory that acts as the boundary for navigation. "
            "For local paths: absolute path (e.g., /app/storage/folder). "
            "For S3: s3:// URI (e.g., s3://bucket/prefix)"
        )
    ),
    s3_client=Depends(get_s3_client),
) -> FileBrowserData:
    """
    Browse files and folders at the specified URI.

    For local storage:
    - Paths are relative to storage_root
    - No navigation above storage_root is allowed

    For S3:
    - Full s3:// URI is required
    - No navigation outside the initial bucket is allowed
    """
    return services.list_files(uri=uri, storage_root=storage_root, s3_client=s3_client)
