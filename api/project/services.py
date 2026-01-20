"""
Services for the Project API
"""

import boto3
import yaml
from datetime import datetime
from typing import Literal
from fastapi import HTTPException, status
from pydantic import PositiveInt
from pytz import timezone
from sqlmodel import Session, func, select
from opensearchpy import OpenSearch
from botocore.exceptions import NoCredentialsError, ClientError
from api.settings.services import get_setting_value

from core.utils import define_search_body
from api.project.models import (
    Project,
    ProjectAttribute,
    ProjectCreate,
    ProjectPublic,
    ProjectsPublic,
    PipelineConfig,
    PipelineConfigsResponse,
)
from api.search.models import SearchDocument
from api.search.services import add_object_to_index, delete_index


def generate_project_id(*, session: Session) -> str:
    """
    Generate a unique project_id.
    This ID could be anything as long as its unique and human-readable.
    In this case, we generate an ID with the format P-YYYYMMDD-NNNN
    """
    # Prefix out of todays date (e.g., "P-20250717-")
    now = datetime.now(timezone("US/Eastern"))
    prefix = f"P-{now:%Y%m%d}-"

    # Find last project with today's date
    project = session.exec(
        select(Project)
        .where(Project.project_id.like(f"{prefix}%"))
        .order_by(Project.project_id.desc())
        .limit(1)
    ).one_or_none()

    if not project:
        return f"{prefix}0001"

    # Increment the suffix (part after the second hyphen)
    suffix = int(project.project_id.split("-")[2]) + 1
    return f"{prefix}{suffix:04d}"


def create_project(
    *, session: Session, project_in: ProjectCreate, opensearch_client: OpenSearch = None
) -> ProjectPublic:
    """
    Create a new project with optional attributes.
    """
    # Create initial project
    project = Project(
        project_id=generate_project_id(session=session), name=project_in.name
    )
    session.add(project)
    session.flush()

    # Handle attribute mapping
    if project_in.attributes:
        # Prevent duplicate keys
        seen = set()
        keys = [attr.key for attr in project_in.attributes]
        dups = [k for k in keys if k in seen or seen.add(k)]
        if dups:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Duplicate keys ({', '.join(dups)}) are not allowed in project attributes.",
            )

        # Parse and create project attributes
        # linking to new project
        project_attributes = [
            ProjectAttribute(project_id=project.id, key=attr.key, value=attr.value)
            for attr in project_in.attributes
        ]

        # Update database with attribute links
        session.add_all(project_attributes)

    # With orm_mode=True, attributes will be eagerly loaded
    # and mapped to ProjectPublic via response model
    session.commit()
    session.refresh(project)

    # Add project to opensearch
    if opensearch_client:
        search_doc = SearchDocument(id=project.project_id, body=project)
        add_object_to_index(opensearch_client, search_doc, index="projects")

    data_bucket = get_setting_value(session, "DATA_BUCKET_URI")
    results_bucket = get_setting_value(session, "RESULTS_BUCKET_URI")

    return ProjectPublic(
        project_id=project.project_id,
        name=project.name,
        data_folder_uri=f"{data_bucket}/{project.project_id}/",
        results_folder_uri=f"{results_bucket}/{project.project_id}/",
        attributes=project.attributes,
    )


def get_projects(
    *,
    session: Session,
    page: PositiveInt,
    per_page: PositiveInt,
    sort_by: str,
    sort_order: Literal["asc", "desc"],
) -> ProjectsPublic:
    """
    Returns all projects from the database along
    with pagination information.
    """
    # Get total project count
    total_count = session.exec(select(func.count()).select_from(Project)).one()

    # Compute total pages
    total_pages = (total_count + per_page - 1) // per_page  # Ceiling division

    # Determine sort field and direction
    sort_field = getattr(Project, sort_by, Project.id)
    sort_direction = sort_field.asc() if sort_order == "asc" else sort_field.desc()

    # Get project selection
    projects = session.exec(
        select(Project)
        .order_by(sort_direction)
        .limit(per_page)
        .offset((page - 1) * per_page)
    ).all()

    data_bucket = get_setting_value(session, "DATA_BUCKET_URI")
    results_bucket = get_setting_value(session, "RESULTS_BUCKET_URI")

    # Map to public project
    public_projects = [
        ProjectPublic(
            project_id=project.project_id,
            name=project.name,
            data_folder_uri=f"{data_bucket}/{project.project_id}/",
            results_folder_uri=f"{results_bucket}/{project.project_id}/",
            attributes=project.attributes,
        )
        for project in projects
    ]

    return ProjectsPublic(
        data=public_projects,
        total_items=total_count,
        total_pages=total_pages,
        current_page=page,
        per_page=per_page,
        has_next=page < total_pages,
        has_prev=page > 1,
    )


def get_project_by_project_id(session: Session, project_id: str) -> ProjectPublic:
    """
    Returns a single project by its project_id.
    Note: This is different from its internal "id".
    """
    project = session.exec(
        select(Project).where(Project.project_id == project_id)
    ).first()

    if not project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Project {project_id} not found.",
        )

    data_bucket = get_setting_value(session, "DATA_BUCKET_URI")
    results_bucket = get_setting_value(session, "RESULTS_BUCKET_URI")

    return ProjectPublic(
        project_id=project.project_id,
        name=project.name,
        data_folder_uri=f"{data_bucket}/{project.project_id}/",
        results_folder_uri=f"{results_bucket}/{project.project_id}/",
        attributes=project.attributes,
    )


def search_projects(
    session: Session,
    client: OpenSearch,
    query: str,
    page: int,
    per_page: int,
    sort_by: str | None = "name",
    sort_order: Literal["asc", "desc"] | None = "asc",
) -> ProjectsPublic:
    """
    Search for projects
    """
    # Construct the search query
    search_body = define_search_body(query, page, per_page, sort_by, sort_order)

    try:

        response = client.search(index="projects", body=search_body)
        total_items = response["hits"]["total"]["value"]
        total_pages = (total_items + per_page - 1) // per_page  # Ceiling division

        # Unpack search results into ProjectPublic model
        results = []
        for hit in response["hits"]["hits"]:
            source = hit["_source"]
            project = get_project_by_project_id(
                session=session, project_id=source.get("project_id")
            )
            results.append(ProjectPublic.model_validate(project))

        return ProjectsPublic(
            data=results,
            total_items=total_items,
            total_pages=total_pages,
            current_page=page,
            per_page=per_page,
            has_next=page < total_pages,
            has_prev=page > 1,
        )

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e)
        )


def reindex_projects(
    session: Session,
    client: OpenSearch
):
    """
    Index all projects in database with OpenSearch
    """
    delete_index(client, "projects")
    projects = session.exec(
        select(Project).order_by(Project.project_id)
    ).all()
    for project in projects:
        search_doc = SearchDocument(id=project.project_id, body=project)
        add_object_to_index(client, search_doc, index="projects")


def _get_workflow_configs_s3_location(session: Session) -> tuple[str, str]:
    """
    Get the S3 bucket and prefix for project workflow configurations.

    Args:
        session: Database session

    Returns:
        Tuple of (bucket, prefix) where prefix includes the full path with subfolders
    """
    workflow_configs_uri = get_setting_value(
        session,
        "PROJECT_WORKFLOW_CONFIGS_BUCKET_URI"
    )

    # Ensure URI ends with /
    if not workflow_configs_uri.endswith("/"):
        workflow_configs_uri += "/"

    # Parse S3 URI to get bucket and prefix
    s3_path = workflow_configs_uri.replace("s3://", "")
    bucket = s3_path.split("/")[0]
    prefix = "/".join(s3_path.split("/")[1:])

    return bucket, prefix


def list_workflow_configs(session: Session, s3_client=None) -> list[str]:
    """
    List available project workflow configuration files from S3.

    Args:
        session: Database session
        s3_client: Optional boto3 S3 client

    Returns:
        List of workflow configuration filenames (without .yaml extension)
    """
    bucket, prefix = _get_workflow_configs_s3_location(session)

    try:
        if s3_client is None:
            s3_client = boto3.client("s3")

        # List objects in the bucket/prefix
        paginator = s3_client.get_paginator("list_objects_v2")
        page_iterator = paginator.paginate(Bucket=bucket, Prefix=prefix)

        workflow_configs = []

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
                    workflow_id = filename.rsplit(".", 1)[0]
                    workflow_configs.append(workflow_id)

        return sorted(workflow_configs)

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


def get_workflow_config(
    session: Session, workflow_id: str, s3_client=None
) -> PipelineConfig:
    """
    Retrieve a specific workflow configuration from S3.

    Args:
        session: Database session
        workflow_id: The workflow identifier (filename without extension)
        s3_client: Optional boto3 S3 client

    Returns:
        PipelineConfig object
    """
    
    bucket, prefix = _get_workflow_configs_s3_location(session)

    try:
        if s3_client is None:
            s3_client = boto3.client("s3")

        # Try both .yaml and .yml extensions
        key = None
        for ext in [".yaml", ".yml"]:
            potential_key = f"{prefix}{workflow_id}{ext}"
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
                detail=f"Workflow config '{workflow_id}' not found",
            )

        # Parse YAML
        config_data = yaml.safe_load(yaml_content)
        
        # Add workflow_id to the data
        config_data["workflow_id"] = workflow_id

        # Validate and return as PipelineConfig model
        return PipelineConfig(**config_data)

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
            detail=f"Error parsing workflow config: {str(exc)}",
        ) from exc


def get_all_workflow_configs(
    session: Session, s3_client=None
) -> PipelineConfigsResponse:
    """
    Retrieve and parse all workflow configurations from S3.

    Args:
        session: Database session
        s3_client: Optional boto3 S3 client

    Returns:
        PipelineConfigsResponse with list of all configs
    """
    
    # Get list of workflow IDs
    workflow_ids = list_workflow_configs(session=session, s3_client=s3_client)
    
    # Fetch and parse each config
    configs = []
    for workflow_id in workflow_ids:
        try:
            config = get_workflow_config(
                session=session,
                workflow_id=workflow_id,
                s3_client=s3_client
            )
            configs.append(config)
        except HTTPException as e:
            # Log but continue with other configs
            # Could add logging here
            continue
    
    return PipelineConfigsResponse(
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
    
    # Get all workflow configs
    all_configs = get_all_workflow_configs(session=session, s3_client=s3_client)
    
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
