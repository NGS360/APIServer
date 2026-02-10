"""Action API routes."""

from fastapi import APIRouter, Depends, Query, status

from core.deps import SessionDep, get_s3_client
from . import services
from .models import ActionConfig, SelectOption, ActionOption, ActionPlatform

router = APIRouter(prefix="/actions")


@router.post(
    "/config/validate",
    response_model=ActionConfig,
    tags=["Action Endpoints"],
    status_code=status.HTTP_200_OK,
)
def validate_action_config(
    session: SessionDep,
    s3_path: str = Query(
        ...,
        description="S3 path to action config "
        "(s3://bucket/path/to/config.yaml or relative path)"
    ),
    s3_client=Depends(get_s3_client),
) -> ActionConfig:
    """
    Validate an action configuration file from S3.

    Accepts an S3 path to an action configuration file and validates it
    against the ActionConfig schema. Returns the parsed config if valid,
    or error details if invalid.

    Args:
        s3_path: S3 path to the config file. Can be:
            - Full S3 URI: s3://bucket/path/to/config.yaml
            - Relative path: config.yaml or path/to/config.yaml
              (uses default action configs bucket)

    Examples:
        - s3://my-bucket/configs/rna-seq_pipeline.yaml
        - rna-seq_pipeline.yaml
        - custom/wgs_pipeline.yaml
    """
    return services.validate_action_config(
        session=session, s3_path=s3_path, s3_client=s3_client
    )


@router.get(
    "/options",
    response_model=list[SelectOption],
    tags=["Action Endpoints"],
)
def get_action_options() -> list[SelectOption]:
    """
    Get available action options.

    Returns:
        List of available action options with labels, values,
        and descriptions
    """
    # TODO: This shouldn't be hardcoded. I'm not quite sure how we want
    # to handle this but probably with a config setting.
    return [
        SelectOption(
            label="Create Project",
            value="create-project",
            description="Create a new project in one of the "
            "supported platforms",
        ),
        SelectOption(
            label="Export Project Results",
            value="export-project-results",
            description="Export the project results from one of the "
            "supported platforms",
        ),
    ]


@router.get(
    "/platforms",
    response_model=list[SelectOption],
    tags=["Action Endpoints"],
)
def get_action_platforms() -> list[SelectOption]:
    """
    Get available action platforms.

    Returns:
        List of available platforms with labels, values, and descriptions
    """
    # TODO: This shouldn't be hardcoded. We should read a list of
    # supported platforms from a config file or database.
    return [
        SelectOption(
            label="Arvados",
            value="Arvados",
            description="Arvados platform",
        ),
        SelectOption(
            label="SevenBridges",
            value="SevenBridges",
            description="SevenBridges platform",
        ),
    ]


@router.get(
    "/types",
    response_model=list[dict],
    tags=["Action Endpoints"],
)
def get_action_types(
    session: SessionDep,
    action: ActionOption = Query(
        description="Action type"
    ),
    platform: ActionPlatform = Query(
        description="Action platform"
    ),
    s3_client=Depends(get_s3_client),
) -> list[dict]:
    """
    Get available action types based on action and platform.

    Args:
        action: The action type
        platform: The platform

    Returns:
        List of action types with label, value, and project_type
    """
    return services.get_project_types_for_action_and_platform(
        session=session,
        action=action,
        platform=platform,
        s3_client=s3_client
    )
