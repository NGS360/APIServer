"""
Models for the Pipeline API
"""

from typing import List, Dict, Any, Literal
from sqlmodel import SQLModel
from api.jobs.models import AwsBatchConfig

# Type definitions for pipeline actions and platforms
PipelineAction = Literal["create-project", "export-project-results"]
PipelinePlatform = Literal["Arvados", "SevenBridges"]


class PipelineInput(SQLModel):
    """Model for pipeline input configuration."""
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


class PipelineConfig(SQLModel):
    """Model for pipeline workflow configuration."""
    workflow_id: str | None = None
    project_type: str
    project_admins: List[str]
    inputs: List[PipelineInput] | None = None
    platforms: Dict[str, PlatformConfig]
    export_command: str | None = None
    aws_batch: AwsBatchConfig | None = None


class PipelineConfigsResponse(SQLModel):
    """Response model for list of pipeline workflow configurations."""
    configs: List[PipelineConfig]
    total: int


class PipelineOption(SQLModel):
    """Model for pipeline option"""
    label: str
    value: str
    description: str


class PipelineSubmitRequest(SQLModel):
    """Request model for submitting a pipeline job to AWS Batch"""
    action: PipelineAction
    platform: PipelinePlatform
    project_type: str  # The pipeline workflow type (e.g., "RNA-Seq", "WGS")
    # Export reference label, required for export action
    reference: str | None = None
    # Auto-release flag (only valid for export action)
    auto_release: bool | None = None
