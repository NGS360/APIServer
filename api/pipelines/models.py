"""
Models for the Pipeline API
"""

from typing import List, Dict, Any
from sqlmodel import SQLModel


class PipelineInput(SQLModel):
    """Model for pipeline input configuration."""
    name: str
    desc: str
    type: str
    default: Any = None


class PlatformConfig(SQLModel):
    """Model for platform-specific configuration (Arvados, SevenBridges, etc)."""
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


class PipelineConfigsResponse(SQLModel):
    """Response model for list of pipeline workflow configurations."""
    configs: List[PipelineConfig]
    total: int


class PipelineOption(SQLModel):
    """Model for pipeline option"""
    label: str
    value: str
    description: str
