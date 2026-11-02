"""
Models for the Actions API
"""

from enum import Enum
from typing import List, Dict, Any
from sqlmodel import SQLModel, Field
from api.jobs.models import AwsBatchConfig


class ActionOption(str, Enum):
    """Action types"""
    CREATE_PROJECT = "create-project"
    EXPORT_PROJECT_RESULTS = "export-project-results"


class ActionPlatform(str, Enum):
    """Action platform types"""
    ARVADOS = "Arvados"
    SEVENBRIDGES = "SevenBridges"


class ActionInput(SQLModel):
    """Model for action input configuration."""
    name: str
    desc: str
    type: str
    default: Any = None


class PlatformConfig(SQLModel):
    """Model for platform-specific configuration (Arvados, SevenBridges, etc)."""
    create_project_command: str | None = None
    launchers: str | List[str] | None = None
    exports: List[Dict[str, str]] | None = None
    export_command: str | None = None


class ActionAwsBatchConfig(AwsBatchConfig):
    """AWS Batch configuration for an action, which runs as the submitting user."""
    # Hours an API key minted for the submitter stays valid, for a job (such as a
    # pipeline launcher) that calls back into NGS360 as that user. Unset means no
    # key is minted. Sized to the job definition's timeout: the job retires the
    # key when it exits, and the expiry covers a job that is killed first.
    user_api_key_hours: int | None = Field(default=None, gt=0, le=24 * 7)


class ActionConfig(SQLModel):
    """Model for action workflow configuration."""
    workflow_id: str | None = None
    project_type: str
    project_admins: List[str]
    inputs: List[ActionInput] | None = None
    platforms: Dict[str, PlatformConfig]
    export_command: str | None = None
    aws_batch: ActionAwsBatchConfig | None = None


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
    # Export reference label, required for export action
    reference: str | None = None
    # Auto-release flag (only valid for export action)
    auto_release: bool | None = None
