"""
Services for the Tools API
"""

from core.logger import logger
from fastapi import HTTPException, status
import yaml
import boto3
import botocore
from botocore.exceptions import NoCredentialsError, ClientError
from jinja2.sandbox import SandboxedEnvironment
from typing import Dict, Any
from sqlmodel import Session

from api.tools.models import ToolConfig, ToolSubmitBody
from api.settings.services import get_setting_value


def _get_tool_configs_s3_location(session: Session) -> tuple[str, str]:
    """
    Get the S3 bucket and prefix for tool configurations.

    Args:
        session: Database session

    Returns:
        Tuple of (bucket, prefix) where prefix includes the full path with subfolders
    """
    tool_configs_uri = get_setting_value(
        session,
        "TOOL_CONFIGS_BUCKET_URI"
    )

    # Ensure URI ends with /
    if not tool_configs_uri.endswith("/"):
        tool_configs_uri += "/"

    # Parse S3 URI to get bucket and prefix
    s3_path = tool_configs_uri.replace("s3://", "")
    bucket = s3_path.split("/")[0]
    prefix = "/".join(s3_path.split("/")[1:])

    return bucket, prefix


def list_tool_configs(session: Session, s3_client=None) -> list[str]:
    """
    List available tool configuration files from S3.

    Args:
        session: Database session
        s3_client: Optional boto3 S3 client

    Returns:
        List of tool config filenames (without .yaml extension)
    """
    bucket, prefix = _get_tool_configs_s3_location(session)

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


def get_tool_config(session: Session, tool_id: str, s3_client=None) -> ToolConfig:
    """
    Retrieve a specific tool configuration from S3.

    Args:
        session: Database session
        tool_id: The tool identifier (filename without extension)
        s3_client: Optional boto3 S3 client

    Returns:
        ToolConfig object
    """
    bucket, prefix = _get_tool_configs_s3_location(session)

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


def interpolate(str_in: str, inputs: Dict[str, Any]) -> str:
    '''
    Take an input str, and substitute expressions containing variables with
    their actual values provided in inputs. Uses Jinja2 SandboxedEnvironment
    to prevent code execution vulnerabilities.

    :param str_in: String to be interpolated
    :param inputs: Dictionary of tool inputs (key-value pairs with
                   defaults pre-populated)
    :return: String containing substitutions
    '''
    env = SandboxedEnvironment()
    template = env.from_string(str_in)
    str_out = template.render(inputs).strip()
    return str_out


def _submit_job(
    session: Session,
    job_name: str,
    container_overrides: Dict[str, Any],
    job_def: str,
    job_queue: str
) -> dict:
    """
    Submit a job to AWS Batch, and return the job id.

    Args:
        session: Database session for retrieving AWS settings
        job_name: Name of the job to submit
        container_overrides: Container configuration overrides
        job_def: Job definition name
        job_queue: Job queue name
    """
    logger.info(
        f"Submitting job '{job_name}' to AWS Batch queue '{job_queue}' "
        f"with definition '{job_def}'"
    )
    logger.info(f"Container overrides: {container_overrides}")

    aws_region = get_setting_value(session, "AWS_REGION") or "us-east-1"

    try:
        batch_client = boto3.client("batch", region_name=aws_region)
        response = batch_client.submit_job(
            jobName=job_name,
            jobQueue=job_queue,
            jobDefinition=job_def,
            containerOverrides=container_overrides,
        )
    except botocore.exceptions.ClientError as err:
        logger.error(f"Failed to submit job to AWS Batch: {err}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to submit job to AWS Batch: {err}",
        ) from err

    return response


def submit_job(session: Session, tool_body: ToolSubmitBody, s3_client=None) -> dict:
    """
    Submit an AWS Batch job for the specified tool.

    Args:
        session: Database session
        tool_body: The tool execution request containing tool_id,
                   run_barcode, and inputs
        s3_client: Optional boto3 S3 client
    Returns:
        A dictionary containing job submission details.
    """
    tool_config = get_tool_config(
        session=session, tool_id=tool_body.tool_id, s3_client=s3_client
    )

    # Interpolate inputs with aws_batch schema definition
    if not tool_config.aws_batch:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Tool '{tool_body.tool_id}' is not configured for "
                f"AWS Batch execution."
            ),
        )

    job_name = interpolate(tool_config.aws_batch.job_name, tool_body.inputs)
    command = interpolate(tool_config.aws_batch.command, tool_body.inputs)
    container_overrides = {
        "command": command.split(),
        "environment": [
            {
                "name": env.name,
                "value": interpolate(env.value, tool_body.inputs)
            }
            for env in (tool_config.aws_batch.environment or [])
        ],
    }

    # Submit the job to AWS Batch
    response = _submit_job(
        session=session,
        job_name=job_name,
        container_overrides=container_overrides,
        job_def=tool_config.aws_batch.job_definition,
        job_queue=tool_config.aws_batch.job_queue,
    )

    if 'jobId' in response:
        response['jobCommand'] = command

    return response
