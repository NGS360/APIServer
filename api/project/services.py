"""
Services for the Project API
"""

from datetime import datetime
from typing import Literal, TYPE_CHECKING
from fastapi import HTTPException, status
from pydantic import PositiveInt
from pytz import timezone
from sqlmodel import Session, func, select
from opensearchpy import OpenSearch

from api.settings.services import get_setting_value
from api.pipelines.services import get_all_pipeline_configs
from api.pipelines.models import PipelineAction, PipelinePlatform
from api.jobs.services import submit_batch_job

from core.utils import define_search_body, interpolate

if TYPE_CHECKING:
    from api.pipelines.models import PipelineAction, PipelinePlatform
    from api.jobs.models import BatchJob

from api.project.models import (
    Project,
    ProjectAttribute,
    ProjectCreate,
    ProjectUpdate,
    ProjectPublic,
    ProjectsPublic,
)
from api.search.models import SearchDocument
from api.search.services import add_object_to_index, delete_index
from api.samples.models import (
    Sample,
    SampleAttribute,
    SampleCreate,
    SamplePublic,
    SamplesPublic,
    Attribute,
)


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


def update_project(
    *,
    session: Session,
    opensearch_client: OpenSearch,
    project_id: str,
    update_request: ProjectUpdate,
) -> ProjectPublic:
    """
    Update an existing project with optional name and attributes.
    """
    # Fetch the project
    project = session.exec(
        select(Project).where(Project.project_id == project_id)
    ).first()

    if not project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Project {project_id} not found.",
        )

    # Update name if provided
    if update_request.name is not None:
        project.name = update_request.name

    # Handle attributes if provided
    if update_request.attributes is not None:
        # Prevent duplicate keys
        seen = set()
        keys = [attr.key for attr in update_request.attributes]
        dups = [k for k in keys if k in seen or seen.add(k)]
        if dups:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Duplicate keys ({', '.join(dups)}) are not allowed in project attributes.",
            )

        # Delete all existing attributes for this project
        existing_attributes = session.exec(
            select(ProjectAttribute).where(
                ProjectAttribute.project_id == project.id
            )
        ).all()
        for existing_attr in existing_attributes:
            session.delete(existing_attr)

        # Flush to execute DELETEs before INSERTs to avoid constraint violations
        session.flush()

        # Add new attributes
        for attr in update_request.attributes:
            new_attr = ProjectAttribute(
                project_id=project.id,
                key=attr.key,
                value=attr.value,
            )
            session.add(new_attr)

    session.commit()
    session.refresh(project)

    # Update project in opensearch
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


def submit_pipeline_job(
    session: Session,
    project: Project,
    action: "PipelineAction",
    platform: "PipelinePlatform",
    project_type: str,
    username: str,
    reference: str | None = None,
    auto_release: bool | None = None,
    s3_client=None
) -> "BatchJob":
    """
    Submit a pipeline job to AWS Batch.

    This function retrieves the appropriate pipeline configuration, determines which
    command to use based on the action, interpolates template variables, and submits
    the job to AWS Batch.

    Args:
        session: Database session
        project: The project object (already validated)
        action: Pipeline action (create-project or export-project-results)
        platform: Platform name (arvados or sevenbridges)
        project_type: Pipeline type (e.g., RNA-Seq)
        username: Username of the user submitting the job
        reference: Export reference label (required for export action)
        auto_release: Auto-release flag (only valid for export action)
        s3_client: Optional boto3 S3 client

    Returns:
        BatchJob instance

    Raises:
        HTTPException: If validation fails or submission fails
    """
    # Get all pipeline configs and find matching project_type
    all_configs = get_all_pipeline_configs(session, s3_client)
    pipeline_config = None

    for config in all_configs.configs:
        if config.project_type == project_type:
            pipeline_config = config
            break

    if pipeline_config is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Pipeline configuration for project type '{project_type}' not found"
        )

    # Check if platform exists in pipeline config
    if platform not in pipeline_config.platforms:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Platform '{platform}' not configured for project type '{project_type}'"
        )

    platform_config = pipeline_config.platforms[platform]

    # Validate action-specific requirements
    reference_value = None
    if action == PipelineAction.CREATE_PROJECT:
        # Validate that auto_release is not set for create action
        if auto_release is not None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="auto_release parameter is not valid for create-project action"
            )
    elif action == "export-project-results":
        # Default auto_release to False if not provided
        if auto_release is None:
            auto_release = False

        # Validate reference is provided for export
        if not reference:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Reference is required for export-project-results action"
            )

        # Look up reference value from exports list
        if not platform_config.exports:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    f"No exports configured for platform '{platform}' "
                    f"in project type '{project_type}'"
                )
            )

        # Find the matching export entry
        reference_value = None
        for export_item in platform_config.exports:
            # Each export_item is a dict with one key-value pair
            for label, value in export_item.items():
                if label == reference:
                    reference_value = value
                    break
            if reference_value:
                break

        if reference_value is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    f"Reference '{reference}' not found in exports for "
                    f"platform '{platform}' and project type "
                    f"'{project_type}'"
                )
            )

    # Prepare template context with all variables needed for interpolation
    template_context = {
        "username": username,
        "projectid": project.project_id,
        "project_type": project_type,
        "platform": platform,
        "action": action,
        "reference": reference_value,  # Use the looked-up value, not the label
        "auto_release": auto_release
    }

    # Select and interpolate the appropriate command based on action
    if action == PipelineAction.CREATE_PROJECT:
        command_template = platform_config.create_project_command
    else:  # export-project-results
        command_template = platform_config.export_command

    try:
        interpolated_command = interpolate(command_template, template_context)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to interpolate command template: {str(e)}"
        ) from e

    # Check if aws_batch config exists
    if not pipeline_config.aws_batch:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"AWS Batch configuration not found for project type "
                f"'{project_type}'"
            )
        )

    # Interpolate AWS Batch configuration
    try:
        interpolated_job_name = interpolate(pipeline_config.aws_batch.job_name, template_context)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to interpolate job name template: {str(e)}"
        ) from e

    # Prepare container overrides
    container_overrides = {
        "command": interpolated_command.split(),
        "environment": []
    }

    # Add environment variables if specified in aws_batch config
    if pipeline_config.aws_batch.environment:
        for env in pipeline_config.aws_batch.environment:
            try:
                interpolated_env_value = interpolate(env.value, template_context)
                container_overrides["environment"].append({
                    "name": env.name,
                    "value": interpolated_env_value
                })
            except Exception as e:
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail=f"Failed to interpolate environment variable '{env.name}': {str(e)}"
                ) from e

    # Submit job to AWS Batch
    batch_job = submit_batch_job(
        session=session,
        job_name=interpolated_job_name,
        container_overrides=container_overrides,
        job_def=pipeline_config.aws_batch.job_definition,
        job_queue=pipeline_config.aws_batch.job_queue,
        user=username
    )
    return batch_job


def add_sample_to_project(
    session: Session,
    opensearch_client: OpenSearch,
    project: Project,
    sample_in: SampleCreate,
) -> Sample:
    """
    Create a new sample with optional attributes in a project.

    Args:
        session: Database session
        opensearch_client: OpenSearch client for indexing
        project: The project object (already validated)
        sample_in: Sample creation data

    Returns:
        Sample instance
    """
    # Create initial sample
    sample = Sample(sample_id=sample_in.sample_id, project_id=project.project_id)
    session.add(sample)
    session.flush()

    # Handle attribute mapping
    if sample_in.attributes:
        # Prevent duplicate keys
        seen = set()
        keys = [attr.key for attr in sample_in.attributes]
        dups = [k for k in keys if k in seen or seen.add(k)]
        if dups:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Duplicate keys ({', '.join(dups)}) are not allowed in sample attributes.",
            )

        # Create sample attributes
        sample_attributes = [
            SampleAttribute(sample_id=sample.id, key=attr.key, value=attr.value)
            for attr in sample_in.attributes
        ]

        # Update database with attribute links
        session.add_all(sample_attributes)

    session.commit()
    session.refresh(sample)

    # Add sample to opensearch
    if opensearch_client:
        search_doc = SearchDocument(id=str(sample.id), body=sample)
        add_object_to_index(opensearch_client, search_doc, index="samples")

    return sample


def get_project_samples(
    *,
    session: Session,
    project: Project,
    page: PositiveInt,
    per_page: PositiveInt,
    sort_by: str,
    sort_order: Literal["asc", "desc"],
) -> SamplesPublic:
    """
    Get a paginated list of samples for a specific project.

    Args:
        session: Database session
        project: The project object (already validated)
        page: Page number (1-based)
        per_page: Number of items per page
        sort_by: Column name to sort by
        sort_order: Sort direction ('asc' or 'desc')

    Returns:
        SamplesPublic: Paginated list of samples for the project
    """
    # Get the total count of samples for the project
    total_count = session.exec(
        select(func.count()).select_from(Sample).where(Sample.project_id == project.project_id)
    ).one()

    # Compute total pages
    total_pages = (total_count + per_page - 1) // per_page  # Ceiling division

    # Calculate offset for pagination
    offset = (page - 1) * per_page

    # Build the select statement
    statement = select(Sample).where(Sample.project_id == project.project_id)

    # Add sorting
    if hasattr(Sample, sort_by):
        sort_column = getattr(Sample, sort_by)
        if sort_order == "desc":
            sort_column = sort_column.desc()
        statement = statement.order_by(sort_column)

    # Add pagination
    statement = statement.offset(offset).limit(per_page)

    # Execute the query
    samples = session.exec(statement).all()

    # Map to public samples
    public_samples = [
        SamplePublic(
            sample_id=sample.sample_id,
            project_id=sample.project_id,
            attributes=sample.attributes,
        )
        for sample in samples
    ]

    # Collect all unique attribute keys across all samples for data_cols
    data_cols = None
    if samples:
        all_keys = set()
        for sample in samples:
            if sample.attributes:
                for attr in sample.attributes:
                    all_keys.add(attr.key)
        data_cols = sorted(list(all_keys)) if all_keys else None

    return SamplesPublic(
        data=public_samples,
        data_cols=data_cols,
        total_items=total_count,
        total_pages=total_pages,
        current_page=page,
        per_page=per_page,
        has_next=page < total_pages,
        has_prev=page > 1,
    )


def update_sample_in_project(
    session: Session,
    project: Project,
    sample_id: str,
    attribute: Attribute,
) -> SamplePublic:
    """
    Update an existing sample in a project.

    Args:
        session: Database session
        project: The project object (already validated)
        sample_id: ID of the sample to update
        attribute: Attribute to add or update

    Returns:
        Updated sample
    """
    # Fetch the sample
    sample = session.exec(
        select(Sample).where(
            Sample.sample_id == sample_id,
            Sample.project_id == project.project_id
        )
    ).first()

    if not sample:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Sample {sample_id} in project {project.project_id} not found.",
        )

    # Check if the attribute exists
    sample_attribute = session.exec(
        select(SampleAttribute).where(
            SampleAttribute.sample_id == sample.id,
            SampleAttribute.key == attribute.key
        )
    ).first()

    if sample_attribute:
        # Update existing attribute
        sample_attribute.value = attribute.value
    else:
        # Create new attribute
        new_attribute = SampleAttribute(
            sample_id=sample.id,
            key=attribute.key,
            value=attribute.value
        )
        session.add(new_attribute)

    session.commit()
    session.refresh(sample)

    return SamplePublic(
        sample_id=sample.sample_id,
        project_id=sample.project_id,
        attributes=[
            Attribute(key=attr.key, value=attr.value) for attr in (sample.attributes or [])
        ] if sample.attributes else []
    )
