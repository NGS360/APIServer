"""
Routes/endpoints for the Manifest API
"""

from typing import Optional

from fastapi import APIRouter, Depends, Query, Response, status, UploadFile, File
from api.manifest import services
from api.manifest.models import ManifestUploadResponse, ManifestValidationResponse
from core.deps import get_s3_client, SessionDep


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


@router.post(
    "",
    response_model=ManifestUploadResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["Manifest Endpoints"],
)
def upload_manifest(
    s3_path: str = Query(
        ..., description="S3 path where the manifest file should be uploaded"
    ),
    file: UploadFile = File(..., description="Manifest CSV file to upload"),
    s3_client=Depends(get_s3_client),
) -> ManifestUploadResponse:
    """
    Upload a manifest CSV file to the specified S3 path.

    Args:
        s3_path: S3 path where the file should be uploaded
            (e.g., "s3://bucket-name/path/to/manifest.csv")
        file: The manifest CSV file to upload

    Returns:
        ManifestUploadResponse with the uploaded file path and status
    """
    result = services.upload_manifest_file(s3_path, file, s3_client)
    return result


@router.post(
    "/validate",
    response_model=ManifestValidationResponse,
    tags=["Manifest Endpoints"],
)
def validate_manifest(
    session: SessionDep,
    s3_path: str = Query(
        ..., description="S3 path to the manifest CSV file to validate"
    ),
    manifest_version: Optional[str] = Query(
        None, description="Manifest version to validate against (e.g., 'DTS12.1')"
    ),
    files_bucket: Optional[str] = Query(
        None, description="S3 bucket where manifest files are located"
    ),
    files_prefix: Optional[str] = Query(
        None, description="S3 prefix/path where manifest files are located"
    ),
) -> ManifestValidationResponse:
    """
    Validate a manifest CSV file from S3 using the ngs360-manifest-validator Lambda.

    The Lambda function checks the manifest file for:
    - Required fields
    - Data format compliance
    - Value constraints
    - File existence verification

    Args:
        s3_path: S3 path to the manifest CSV file to validate
        manifest_version: Optional manifest version to validate against
        files_bucket: Optional S3 bucket where manifest files are located
        files_prefix: Optional S3 prefix/path for file existence checks

    Returns:
        ManifestValidationResponse with validation status and any errors found
    """
    # Uppercase manifest_version if provided
    if manifest_version:
        manifest_version = manifest_version.upper()

    result = services.validate_manifest_file(
        session=session,
        manifest_path=s3_path,
        manifest_version=manifest_version,
        files_bucket=files_bucket,
        files_prefix=files_prefix,
    )
    return result
