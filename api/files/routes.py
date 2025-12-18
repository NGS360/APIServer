"""
Routes/endpoints for the Files API
"""

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
import io

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


@router.get("/download", tags=["File Endpoints"])
def download_file(
    path: str = Query(
        ...,
        description="S3 URI of the file to download (e.g., s3://bucket/path/file.txt)"
    ),
    s3_client=Depends(get_s3_client),
) -> StreamingResponse:
    """
    Download a file from S3.

    Returns the file as a streaming download with appropriate content type and filename.
    
    Args:
        path: Full S3 URI to the file (e.g., s3://bucket/folder/file.txt)
    
    Returns:
        StreamingResponse with the file content
    """
    file_content, content_type, filename = services.download_file(
        s3_path=path, s3_client=s3_client
    )
    
    # Create a streaming response with the file content
    return StreamingResponse(
        io.BytesIO(file_content),
        media_type=content_type,
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"'
        }
    )
