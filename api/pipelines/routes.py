"""Pipeline API routes."""

from fastapi import APIRouter, Depends, Query, status

from core.deps import SessionDep, get_s3_client
from . import services
from .models import PipelineConfig, PipelineOption, PipelineAction, PipelinePlatform

router = APIRouter(prefix="/pipelines")


@router.post(
    "/validate",
    response_model=PipelineConfig,
    tags=["Pipeline Endpoints"],
    status_code=status.HTTP_200_OK,
)
def validate_pipeline_config(
    session: SessionDep,
    s3_path: str = Query(
        ...,
        description="S3 path to pipeline config "
        "(s3://bucket/path/to/config.yaml or relative path)"
    ),
    s3_client=Depends(get_s3_client),
) -> PipelineConfig:
    """
    Validate a pipeline configuration file from S3.

    Accepts an S3 path to a pipeline configuration file and validates it
    against the PipelineConfig schema. Returns the parsed config if valid,
    or error details if invalid.

    Args:
        s3_path: S3 path to the config file. Can be:
            - Full S3 URI: s3://bucket/path/to/config.yaml
            - Relative path: config.yaml or path/to/config.yaml
              (uses default pipeline configs bucket)

    Examples:
        - s3://my-bucket/configs/rna-seq_pipeline.yaml
        - rna-seq_pipeline.yaml
        - custom/wgs_pipeline.yaml
    """
    return services.validate_pipeline_config(
        session=session, s3_path=s3_path, s3_client=s3_client
    )


@router.get(
    "/actions",
    response_model=list[PipelineOption],
    tags=["Pipeline Endpoints"],
)
def get_pipeline_actions() -> list[PipelineOption]:
    """
    Get available pipeline actions.

    Returns:
        List of available pipeline actions with labels, values,
        and descriptions
    """
    # TODO: This shouldn't be hardcoded. I'm not quite sure how we want
    # to handle this but probably with a config setting.
    return [
        PipelineOption(
            label="Create Project",
            value="create-project",
            description="Create a new project in one of the "
            "supported platforms",
        ),
        PipelineOption(
            label="Export Project Results",
            value="export-project-results",
            description="Export the project results from one of the "
            "supported platforms",
        ),
    ]


@router.get(
    "/platforms",
    response_model=list[PipelineOption],
    tags=["Pipeline Endpoints"],
)
def get_pipeline_platforms() -> list[PipelineOption]:
    """
    Get available pipeline platforms.

    Returns:
        List of available platforms with labels, values, and descriptions
    """
    # TODO: This shouldn't be hardcoded. We should read a list of
    # supported platforms from a config file or database.
    return [
        PipelineOption(
            label="Arvados",
            value="Arvados",
            description="Arvados platform",
        ),
        PipelineOption(
            label="SevenBridges",
            value="SevenBridges",
            description="SevenBridges platform",
        ),
    ]


@router.get(
    "/types",
    response_model=list[dict],
    tags=["Pipeline Endpoints"],
)
def get_pipeline_types(
    session: SessionDep,
    action: PipelineAction = Query(
        description="Pipeline action"
    ),
    platform: PipelinePlatform = Query(
        description="Pipeline platform"
    ),
    s3_client=Depends(get_s3_client),
) -> list[dict]:
    """
    Get available pipeline types based on action and platform.

    Args:
        action: The pipeline action
        platform: The platform

    Returns:
        List of pipeline types with label, value, and project_type
    """
    return services.get_project_types_for_action_and_platform(
        session=session,
        action=action,
        platform=platform,
        s3_client=s3_client
    )
