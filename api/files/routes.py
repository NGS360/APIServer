"""
Routes/endpoints for the Files API
"""

from fastapi import APIRouter, Depends, File, Form, Query, UploadFile, status

from api.files.models import FileBrowserData
import api.files.services as services
from core.deps import get_s3_client

router = APIRouter(prefix="/files", tags=["File Endpoints"])


@router.post(
    "/upload",
    response_model=FileBrowserData,
    status_code=status.HTTP_201_CREATED,
    summary="Upload a file to the specified URI",
    tags=["File Endpoints"]
)
async def upload_file(
    uri: str = Form(
        ..., description="Destination URI (e.g., s3://bucket/folder/file.txt or local path/file.txt)"
    ),
    file: UploadFile = File(..., description="File to upload"),
    s3_client=Depends(get_s3_client),
) -> FileBrowserData:
    """
    Upload a file to the specified URI.
    """
    file_content = await file.read()
    return services.upload_file(uri=uri, file_content=file_content, s3_client=s3_client)


@router.get("/list", response_model=FileBrowserData, tags=["File Endpoints"])
def list_files(
    uri: str = Query(..., description="URI to list (e.g., s3://bucket/folder/)"),
    s3_client=Depends(get_s3_client),
) -> FileBrowserData:
    """
    Browse files and folders at the specified URI.
    """
    return services.list_files(uri=uri, s3_client=s3_client)
