"""
Models for the Actions API
"""

from enum import Enum
from typing import List, Dict, Any
from sqlmodel import SQLModel
from api.jobs.models import AwsBatchConfig, AwsBatchEnvironment


class ActionOption(str, Enum):
    """Action types"""
    CREATE_PROJECT = "create-project"
    EXPORT_PROJECT_RESULTS = "export-project-results"
    LAUNCH_PIPELINE = "launch-pipeline"


class ActionPlatform(str, Enum):
    """Action platform types"""
    ARVADOS = "Arvados"
    SEVENBRIDGES = "SevenBridges"
    # Workflows run on AWS HealthOmics through the GA4GH WES service. Named for
    # the platform as PAML and the pipeline launchers know it, not the engine.
    NGS360 = "NGS360"


class ActionInput(SQLModel):
    """Model for action input configuration."""
    name: str
    desc: str
    type: str
    default: Any = None


class ActionBatchOverride(SQLModel):
    """What one action on one platform changes about the project type's aws_batch."""
    job_definition: str | None = None
    job_queue: str | None = None
    # Added to the project type's environment, not replacing it
    environment: List[AwsBatchEnvironment] | None = None


class PlatformConfig(SQLModel):
    """Model for platform-specific configuration (Arvados, SevenBridges, etc)."""
    create_project_command: str | None = None
    launchers: str | List[str] | None = None
    exports: List[Dict[str, str]] | None = None
    export_command: str | None = None
    # Reference models a pipeline can be launched against, each a single
    # {label: reference} pair as in `exports`. The launcher resolves the
    # reference itself, so these must be ones its own configuration knows.
    references: List[Dict[str, str]] | None = None
    # Runs the pipeline launcher. Only for a platform with nowhere of its own to
    # start one: on Arvados and SevenBridges the launcher is an app the user runs
    # on the platform, after create-project has put it in their project.
    launch_command: str | None = None
    # Per-action changes to the project type's aws_batch, for an action that
    # cannot run in the shared job definition -- a launcher is its own image.
    aws_batch: Dict[ActionOption, ActionBatchOverride] | None = None


class ActionConfig(SQLModel):
    """Model for action workflow configuration."""
    workflow_id: str | None = None
    project_type: str
    project_admins: List[str]
    inputs: List[ActionInput] | None = None
    platforms: Dict[str, PlatformConfig]
    export_command: str | None = None
    aws_batch: AwsBatchConfig | None = None


class ActionConfigsResponse(SQLModel):
    """Response model for list of action workflow configurations."""
    configs: List[ActionConfig]
    total: int


class SelectOption(SQLModel):
    """Model for UI select/dropdown option"""
    label: str
    value: str
    description: str


class ActionSubmitRequest(SQLModel):
    """Request model for submitting an action job to AWS Batch"""
    action: ActionOption
    platform: ActionPlatform
    project_type: str  # The workflow type (e.g., "RNA-Seq", "WGS")
    # Reference label: an export for the export action, a reference model for
    # the launch action. Required for both.
    reference: str | None = None
    # Auto-release flag (only valid for export action)
    auto_release: bool | None = None
