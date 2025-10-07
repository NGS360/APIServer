"""
Routes/endpoints for the Files API
"""

from fastapi import APIRouter, Depends, Query

from api.files.models import FileBrowserData
from api.files import services
from core.deps import get_s3_client

router = APIRouter(prefix="/files", tags=["File Endpoints"])


@router.get("/list", response_model=FileBrowserData, tags=["File Endpoints"])
def list_files(
    uri: str = Query(
        ...,
        description="URI to list (e.g., s3://bucket/folder/)"
    ),
    s3_client=Depends(get_s3_client),
) -> FileBrowserData:
    """
    Browse files and folders at the specified URI.

    For S3:
    - Full s3:// URI is required
    - No navigation outside the initial uri is allowed
    """
    return services.list_files(uri=uri, s3_client=s3_client)
