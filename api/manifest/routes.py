"""
Routes/endpoints for the Manifest API
"""

from fastapi import APIRouter, Depends, Query, Response, status
from api.manifest import services
from core.deps import get_s3_client


router = APIRouter(prefix="/manifest", tags=["Manifest Endpoints"])


@router.get("", response_model=str, tags=["Manifest Endpoints"])
def get_latest_manifest(
    s3_path: str = Query(
        ..., description="S3 bucket path to search for manifest files"
    ),
    s3_client=Depends(get_s3_client),
) -> str:
    """
    Retrieve the latest manifest file path from the specified S3 bucket.

    Searches recursively through the bucket/prefix for files that:
    - Contain "manifest" (case-insensitive)
    - End with ".csv"

    Returns the full S3 path of the most recent matching file.

    Args:
        s3_path: S3 path to search (e.g., "s3://bucket-name/path/to/manifests")

    Returns:
        Full S3 path to the latest manifest file
    """
    manifest_path = services.get_latest_manifest_file(s3_path, s3_client)

    if manifest_path is None:
        # Return 204 No Content if no manifest found
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    return manifest_path
