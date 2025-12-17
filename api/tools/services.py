"""
Services for the Tools API
"""

from fastapi import HTTPException, status
import yaml
import boto3
from botocore.exceptions import NoCredentialsError, ClientError

from api.tools.models import ToolConfig
from core.config import get_settings


def _get_tool_configs_s3_location() -> tuple[str, str]:
    """
    Get the S3 bucket and prefix for tool configurations.

    Returns:
        Tuple of (bucket, prefix) where prefix includes the full path with subfolders
    """
    settings = get_settings()
    tool_configs_uri = settings.TOOL_CONFIGS_BUCKET_URI

    # Ensure URI ends with /
    if not tool_configs_uri.endswith("/"):
        tool_configs_uri += "/"

    # Parse S3 URI to get bucket and prefix
    s3_path = tool_configs_uri.replace("s3://", "")
    bucket = s3_path.split("/")[0]
    prefix = "/".join(s3_path.split("/")[1:])

    return bucket, prefix


def list_tool_configs(s3_client=None) -> list[str]:
    """
    List available tool configuration files from S3.

    Returns:
        List of tool config filenames (without .yaml extension)
    """
    bucket, prefix = _get_tool_configs_s3_location()

    try:
        if s3_client is None:
            s3_client = boto3.client("s3")

        # List objects in the bucket/prefix
        paginator = s3_client.get_paginator("list_objects_v2")
        page_iterator = paginator.paginate(Bucket=bucket, Prefix=prefix)

        tool_configs = []

        for page in page_iterator:
            for obj in page.get("Contents", []):
                key = obj["Key"]

                # Skip if this is just the prefix itself
                if key == prefix:
                    continue

                # Get filename from the key
                filename = key[len(prefix):] if prefix else key

                # Only include .yaml or .yml files
                if filename.endswith((".yaml", ".yml")):
                    # Remove extension and add to list
                    tool_id = filename.rsplit(".", 1)[0]
                    tool_configs.append(tool_id)

        return sorted(tool_configs)

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
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Unexpected error listing tool configs: {str(exc)}",
        ) from exc


def get_tool_config(tool_id: str, s3_client=None) -> ToolConfig:
    """
    Retrieve a specific tool configuration from S3.

    Args:
        tool_id: The tool identifier (filename without extension)
        s3_client: Optional boto3 S3 client

    Returns:
        ToolConfig object
    """
    bucket, prefix = _get_tool_configs_s3_location()

    try:
        if s3_client is None:
            s3_client = boto3.client("s3")

        # Try both .yaml and .yml extensions
        key = None
        for ext in [".yaml", ".yml"]:
            potential_key = f"{prefix}{tool_id}{ext}"
            try:
                # Try to get the object directly instead of using head_object
                response = s3_client.get_object(Bucket=bucket, Key=potential_key)
                key = potential_key
                yaml_content = response["Body"].read().decode("utf-8")
                break
            except ClientError as e:
                error_code = e.response["Error"]["Code"]
                if error_code in ["NoSuchKey", "404"]:
                    continue  # Try next extension
                else:
                    raise  # Re-raise other errors

        if key is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Tool config '{tool_id}' not found",
            )

        # Parse YAML
        config_data = yaml.safe_load(yaml_content)

        # Validate and return as ToolConfig model
        return ToolConfig(**config_data)

    except HTTPException:
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
        elif error_code == "NoSuchKey":
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Tool config '{tool_id}' not found",
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
    except yaml.YAMLError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Invalid YAML format in tool config: {str(exc)}",
        ) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Unexpected error retrieving tool config: {str(exc)}",
        ) from exc
