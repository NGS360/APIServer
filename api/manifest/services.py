"""
Services for the Manifest API
"""

import json
from fastapi import HTTPException, status, UploadFile
import boto3
from botocore.exceptions import NoCredentialsError, ClientError
from api.manifest.models import ManifestUploadResponse, ManifestValidationResponse
from api.settings.services import get_setting_value
from core.config import get_settings
from core.deps import SessionDep
from core.logger import logger


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


def upload_manifest_file(
    s3_path: str, file: UploadFile, s3_client=None
) -> ManifestUploadResponse:
    """
    Upload a manifest CSV file to S3.

    Args:
        s3_path: The S3 path where the file should be uploaded
        (e.g., "s3://bucket-name/path/to/manifest.csv")
        file: The uploaded file object
        s3_client: Optional boto3 S3 client

    Returns:
        ManifestUploadResponse with the uploaded file path and status
    """
    try:
        # Validate file type
        if not file.filename or not file.filename.lower().endswith('.csv'):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Only CSV files are allowed for manifest uploads"
            )

        # Parse the S3 path
        bucket, key = _parse_s3_path(s3_path)

        # If the key ends with '/' or is empty, append the filename
        if key.endswith('/') or not key:
            key = f"{key}{file.filename}"
        # If key doesn't end with .csv, assume it's a directory and append filename
        elif not key.lower().endswith('.csv'):
            key = f"{key}/{file.filename}"

        # Initialize S3 client (use provided or create new)
        if s3_client is None:
            s3_client = boto3.client("s3")

        # Read file content
        content = file.file.read()

        # Upload the file to S3
        s3_client.put_object(
            Bucket=bucket,
            Key=key,
            Body=content,
            ContentType='text/csv'
        )

        # Construct the full S3 path for the response
        uploaded_path = f"s3://{bucket}/{key}"

        return ManifestUploadResponse(
            status="success",
            message="Manifest file uploaded successfully",
            path=uploaded_path,
            filename=file.filename
        )

    except HTTPException:
        # Re-raise HTTPException without catching it
        raise
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
            detail=f"Unexpected error uploading manifest: {str(exc)}",
        ) from exc


def validate_manifest_file(
    session: SessionDep,
    s3_path: str
) -> ManifestValidationResponse:
    """
    Validate a manifest CSV file from S3.

    Args:
        session: Database session
        s3_path: S3 path to the manifest CSV file to validate

    Returns:
        ManifestValidationResponse with validation status and any errors found
    """
    # Placeholder for validation logic
    # The actual validation logic would go here

    # Call to lambda function for validation (placeholder)
    lambda_function_name = get_setting_value(session, "MANIFEST_VALIDATION_LAMBDA")
    logger.info(f"Invoking Lambda function: {lambda_function_name} for manifest validation")

    # Convert the payload dictionary to a JSON string and then to bytes
    payload_bytes = bytes(json.dumps({"s3_path": s3_path}), encoding='utf8')

    # Initialize the Lambda client
    # Boto3 uses credentials from the environment or a configured profile
    client = boto3.client('lambda', region_name=get_settings().AWS_REGION)

    # Invoke the function
    response = client.invoke(
        FunctionName=lambda_function_name,
        InvocationType='RequestResponse',  # Use 'Event' for async invocation
        Payload=payload_bytes
    )

    # Read and decode the payload from the response
    response_payload = json.loads(response['Payload'].read().decode('utf-8'))
    return ManifestValidationResponse.model_validate(response_payload)
