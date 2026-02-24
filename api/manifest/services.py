"""
Services for the Manifest API
"""

import json
from typing import Optional
from fastapi import HTTPException, status, UploadFile
import boto3
from botocore.exceptions import NoCredentialsError, ClientError
from api.manifest.models import ManifestUploadResponse, ManifestValidationResponse
from api.settings.services import get_setting_value
from core.config import get_settings
from core.deps import SessionDep
from core.logger import logger


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
    manifest_uri: str,
    files_uri: str,
    manifest_version: Optional[str] = None
) -> ManifestValidationResponse:
    """
    Validate a manifest CSV file from S3 by invoking a Lambda function.

    Args:
        session: Database session
        manifest_uri: S3 path to the manifest CSV file to validate
        manifest_version: Optional manifest version to validate against
        files_uri: S3 path where files described in manifest are located

    Returns:
        ManifestValidationResponse with validation status and any errors found
    """
    # Get Lambda function name from settings, fall back to default
    lambda_function_name = (
        get_setting_value(session, "MANIFEST_VALIDATION_LAMBDA")
        or "ngs360-manifest-validator"
    )
    logger.info(
        "Invoking Lambda function: %s for manifest validation of %s",
        lambda_function_name,
        manifest_uri
    )

    try:
        # Get AWS region from settings
        settings = get_settings()
        region = settings.AWS_REGION

        # Create Lambda client
        lambda_client = boto3.client("lambda", region_name=region)

        # Prepare payload for Lambda function
        # Lambda expects: manifest_path, files_bucket, manifest_version (optional),
        # files_prefix (optional), available_pipelines (optional)
        payload = {
            "manifest_uri": manifest_uri,
            "files_uri": files_uri,
        }

        # Add optional parameters if provided
        if manifest_version:
            payload["manifest_version"] = manifest_version

        # Invoke Lambda function synchronously
        response = lambda_client.invoke(
            FunctionName=lambda_function_name,
            InvocationType="RequestResponse",
            Payload=json.dumps(payload)
        )

        # Read and parse Lambda response
        response_payload = json.loads(response["Payload"].read().decode("utf-8"))
        logger.debug("Lambda response: %s", response_payload)

        # Check for Lambda execution errors (unhandled exceptions)
        if "FunctionError" in response:
            error_message = response_payload.get(
                "errorMessage",
                "Unknown Lambda execution error"
            )
            logger.error("Lambda function error: %s", error_message)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Lambda validation error: {error_message}"
            )

        # Parse the Lambda response body if it contains a nested body field
        # (API Gateway-style Lambda responses have body as JSON string)
        if "body" in response_payload:
            if isinstance(response_payload["body"], str):
                validation_result = json.loads(response_payload["body"])
            else:
                validation_result = response_payload["body"]
        else:
            # Direct invocation returns raw body with statusCode embedded
            validation_result = response_payload

        # Check for Lambda-level errors (validation errors, missing params, etc.)
        if not validation_result.get("success", True):
            error_msg = validation_result.get("error", "Unknown validation error")
            error_type = validation_result.get("error_type", "ValidationError")
            lambda_status = validation_result.get("statusCode", 400)

            logger.error("Lambda returned error: %s - %s", error_type, error_msg)

            # Map Lambda status codes to HTTP exceptions
            if lambda_status == 400:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Validation request error: {error_msg}"
                )
            elif lambda_status == 404:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Manifest file not found: {error_msg}"
                )
            elif lambda_status == 503:
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail=f"Service unavailable: {error_msg}"
                )
            else:
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail=f"Validation error: {error_msg}"
                )

        # Build response from Lambda result
        # Lambda returns: validation_passed, messages, errors, warnings
        # API returns: valid, message, error, warning
        return ManifestValidationResponse(
            valid=validation_result.get("validation_passed", False),
            message=validation_result.get("messages", {}),
            error=validation_result.get("errors", {}),
            warning=validation_result.get("warnings", {})
        )

    except NoCredentialsError as exc:
        logger.error("AWS credentials not found for Lambda invocation")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="AWS credentials not found. Please configure AWS credentials.",
        ) from exc
    except ClientError as exc:
        error_code = exc.response["Error"]["Code"]
        error_message = exc.response["Error"]["Message"]
        logger.error("Lambda ClientError: %s - %s", error_code, error_message)

        if error_code == "ResourceNotFoundException":
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Lambda function not found: {lambda_function_name}",
            ) from exc
        elif error_code == "AccessDeniedException":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Access denied to Lambda function: {lambda_function_name}",
            ) from exc
        else:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Lambda error: {error_message}",
            ) from exc
    except json.JSONDecodeError as exc:
        logger.error("Failed to parse Lambda response: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to parse validation response from Lambda",
        ) from exc
    except HTTPException:
        # Re-raise HTTPException without modification
        raise
    except Exception as exc:
        logger.error("Unexpected error invoking Lambda: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Unexpected error during manifest validation: {str(exc)}",
        ) from exc
