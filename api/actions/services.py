"""Action API services."""

import boto3
import yaml
from botocore.exceptions import ClientError, NoCredentialsError
from fastapi import HTTPException, status
from sqlmodel import Session

from api.settings.services import get_setting_value
from .models import ActionConfig, ActionConfigsResponse


def _get_action_configs_s3_location(session: Session) -> tuple[str, str]:
    """
    Get the S3 bucket and prefix for project action configurations.

    Args:
        session: Database session

    Returns:
        Tuple of (bucket, prefix) where prefix includes the full path with subfolders
    """
    action_configs_uri = get_setting_value(
        session,
        "PROJECT_WORKFLOW_CONFIGS_BUCKET_URI"
    )

    # Ensure URI ends with /
    if not action_configs_uri.endswith("/"):
        action_configs_uri += "/"

    # Parse S3 URI to get bucket and prefix
    s3_path = action_configs_uri.replace("s3://", "")
    bucket = s3_path.split("/")[0]
    prefix = "/".join(s3_path.split("/")[1:])

    return bucket, prefix


def list_action_configs(session: Session, s3_client=None) -> list[str]:
    """
    List available project action configuration files from S3.

    Args:
        session: Database session
        s3_client: Optional boto3 S3 client

    Returns:
        List of action configuration filenames (without .yaml extension)
    """
    bucket, prefix = _get_action_configs_s3_location(session)

    try:
        if s3_client is None:
            s3_client = boto3.client("s3")

        # List objects in the bucket/prefix
        paginator = s3_client.get_paginator("list_objects_v2")
        page_iterator = paginator.paginate(Bucket=bucket, Prefix=prefix)

        action_configs = []

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
                    action_id = filename.rsplit(".", 1)[0]
                    action_configs.append(action_id)

        return sorted(action_configs)

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


def get_action_config(
    session: Session, action_id: str, s3_client=None
) -> ActionConfig:
    """
    Retrieve a specific action configuration from S3.

    Args:
        session: Database session
        action_id: The action identifier (filename without extension)
        s3_client: Optional boto3 S3 client

    Returns:
        ActionConfig object
    """

    bucket, prefix = _get_action_configs_s3_location(session)

    try:
        if s3_client is None:
            s3_client = boto3.client("s3")

        # Try both .yaml and .yml extensions
        key = None
        for ext in [".yaml", ".yml"]:
            potential_key = f"{prefix}{action_id}{ext}"
            try:
                response = s3_client.get_object(Bucket=bucket, Key=potential_key)
                key = potential_key
                yaml_content = response["Body"].read().decode("utf-8")
                break
            except ClientError as e:
                error_code = e.response["Error"]["Code"]
                if error_code in ["NoSuchKey", "404"]:
                    continue  # Try next extension
                else:
                    raise

        if key is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Action config '{action_id}' not found",
            )

        # Parse YAML
        config_data = yaml.safe_load(yaml_content)

        # Add action_id to the data
        config_data["workflow_id"] = action_id

        # Validate and return as ActionConfig model
        return ActionConfig(**config_data)

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
            detail=f"Error parsing action config: {str(exc)}",
        ) from exc


def get_all_action_configs(
    session: Session, s3_client=None
) -> ActionConfigsResponse:
    """
    Retrieve and parse all action configurations from S3.

    Args:
        session: Database session
        s3_client: Optional boto3 S3 client

    Returns:
        ActionConfigsResponse with list of all configs
    """

    # Get list of action IDs
    action_ids = list_action_configs(session=session, s3_client=s3_client)

    # Fetch and parse each config
    configs = []
    for action_id in action_ids:
        try:
            config = get_action_config(
                session=session,
                action_id=action_id,
                s3_client=s3_client
            )
            configs.append(config)
        except HTTPException:
            # Log but continue with other configs
            # Could add logging here
            continue

    return ActionConfigsResponse(
        configs=configs,
        total=len(configs)
    )


def get_project_types_for_action_and_platform(
    session: Session,
    action: str,
    platform: str,
    s3_client=None
) -> list[dict[str, str]]:
    """
    Get available project types based on action and platform.

    Args:
        session: Database session
        action: The action type
        platform: The platform name
        s3_client: Optional boto3 S3 client

    Returns:
        List of dictionaries with project type information
    """
    # Normalize platform name to match YAML keys
    platform_map = {
        'arvados': 'Arvados',
        'sevenbridges': 'SevenBridges'
    }

    platform_key = platform_map.get(platform.lower())
    if not platform_key:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid platform: {platform}. Must be 'arvados' or 'sevenbridges'"
        )

    # Get all action configs
    all_configs = get_all_action_configs(session=session, s3_client=s3_client)

    result = []

    for config in all_configs.configs:
        # Check if the platform exists in this config
        if platform_key not in config.platforms:
            continue

        platform_config = config.platforms[platform_key]

        if action == 'export-project-results':
            # For export action, return the exports list
            if platform_config.exports:
                for export_item in platform_config.exports:
                    # Each export item is a dict with one key-value pair
                    for label, value in export_item.items():
                        result.append({
                            'label': label,
                            'value': value,
                            'project_type': config.project_type
                        })

        elif action == 'create-project':
            # For create action, return the project_type if platform is listed
            result.append({
                'label': config.project_type,
                'value': config.project_type,
                'project_type': config.project_type
            })

    # Remove duplicates based on label and value
    unique_results = []
    seen = set()
    for item in result:
        key = (item['label'], item['value'])
        if key not in seen:
            seen.add(key)
            unique_results.append(item)

    return unique_results


def validate_action_config(
    session: Session, s3_path: str, s3_client=None
) -> ActionConfig:
    """
    Validate an action configuration from S3 against the ActionConfig schema.

    Args:
        session: Database session
        s3_path: S3 path to the config file (s3://bucket/path/to/config.yaml or path/to/config.yaml)
        s3_client: Optional boto3 S3 client

    Returns:
        ActionConfig object if valid

    Raises:
        HTTPException: If validation fails with details about the errors
    """
    from pydantic import ValidationError

    # Parse S3 path
    if s3_path.startswith("s3://"):
        # Format: s3://bucket/key
        parts = s3_path[5:].split("/", 1)
        if len(parts) != 2:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid S3 path format. Expected: s3://bucket/path/to/file.yaml"
            )
        bucket, key = parts
    else:
        # Use default bucket and treat path as key
        bucket, prefix = _get_action_configs_s3_location(session)
        key = f"{prefix}{s3_path}" if not s3_path.startswith(prefix) else s3_path

    try:
        if s3_client is None:
            s3_client = boto3.client("s3")

        # Fetch file from S3
        response = s3_client.get_object(Bucket=bucket, Key=key)
        config_content = response["Body"].read().decode("utf-8")

        # Parse YAML
        parsed_config = yaml.safe_load(config_content)

        # Validate with Pydantic - let it handle all validation
        return ActionConfig(**parsed_config)

    except ValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=exc.errors()
        ) from exc
    except ClientError as e:
        error_code = e.response["Error"]["Code"]
        if error_code in ["NoSuchKey", "404"]:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Config file not found at s3://{bucket}/{key}"
            ) from e
        elif error_code == "AccessDenied":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Access denied to s3://{bucket}/{key}"
            ) from e
        elif error_code == "NoSuchBucket":
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"S3 bucket not found: {bucket}",
            ) from e
        else:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"S3 error: {e.response['Error']['Message']}",
            ) from e
    except yaml.YAMLError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid YAML format: {str(exc)}"
        ) from exc
