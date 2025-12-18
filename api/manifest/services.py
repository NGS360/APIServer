"""
Services for the Manifest API
"""

from fastapi import HTTPException, status
import boto3
from botocore.exceptions import NoCredentialsError, ClientError


def _parse_s3_path(s3_path: str) -> tuple[str, str]:
    """Parse S3 path into bucket and prefix"""
    if not s3_path.startswith("s3://"):
        raise ValueError("Invalid S3 path format. Must start with s3://")

    # Remove s3:// prefix
    path_without_scheme = s3_path[5:]

    # Check for empty path after s3://
    if not path_without_scheme:
        raise ValueError("Invalid S3 path format. Bucket name is required")

    # Check for leading slash (s3:///)
    if path_without_scheme.startswith("/"):
        raise ValueError("Invalid S3 path format. Bucket name cannot start with /")

    # Check for double slashes anywhere in the path
    if "//" in path_without_scheme:
        raise ValueError("Invalid S3 path format. Path cannot contain double slashes")

    # Split into bucket and key
    if "/" in path_without_scheme:
        bucket, key = path_without_scheme.split("/", 1)
    else:
        bucket = path_without_scheme
        key = ""

    return bucket, key


def get_latest_manifest_file(s3_path: str, s3_client=None) -> str | None:
    """
    Recursively search an S3 bucket/prefix for the most recent manifest CSV file.

    Args:
        s3_path: The S3 path to search (e.g., "s3://bucket-name/path/to/manifests")
        s3_client: Optional boto3 S3 client

    Returns:
        Full S3 path of the most recent manifest file, or None if no manifest found

    Raises:
        HTTPException: For various S3 errors (credentials, access, etc.)
    """
    try:
        # Parse the S3 path
        bucket, prefix = _parse_s3_path(s3_path)

        # Initialize S3 client (use provided or create new)
        if s3_client is None:
            s3_client = boto3.client("s3")

        # List all objects recursively (no Delimiter to get all files)
        paginator = s3_client.get_paginator("list_objects_v2")
        page_iterator = paginator.paginate(Bucket=bucket, Prefix=prefix)

        # Track the most recent manifest file
        latest_manifest = None
        latest_modified = None

        for page in page_iterator:
            # Handle actual files
            for obj in page.get("Contents", []):
                key = obj["Key"]

                # Check if file matches criteria:
                # 1. Contains "manifest" (case-insensitive)
                # 2. Ends with ".csv"
                if "manifest" in key.lower() and key.lower().endswith(".csv"):
                    mod_time = obj["LastModified"]

                    # Track the most recent file
                    if latest_modified is None or mod_time > latest_modified:
                        latest_modified = mod_time
                        latest_manifest = f"s3://{bucket}/{key}"

        return latest_manifest

    except NoCredentialsError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="AWS credentials not found. Please configure AWS credentials.",
        ) from exc
    except ClientError as exc:
        error_code = exc.response["Error"]["Code"]
        if error_code == "NoSuchBucket":
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"S3 bucket not found: {bucket}",
            ) from exc
        elif error_code == "AccessDenied":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Access denied to S3 bucket: {bucket}",
            ) from exc
        else:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"S3 error: {exc.response['Error']['Message']}",
            ) from exc
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        ) from e
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Unexpected error searching for manifest: {str(exc)}",
        ) from exc
