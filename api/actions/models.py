"""
Models for the Actions API
"""

from enum import Enum
from typing import List, Dict, Any
from sqlmodel import SQLModel, Field
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
    # For an action that runs a command. A launch runs in the job definition its
    # workflow's deployment names, whatever is set here.
    job_definition: str | None = None
    job_queue: str | None = None
    # Added to the project type's environment, not replacing it
    environment: List[AwsBatchEnvironment] | None = None
    # Hours an API key minted for the submitter stays valid, for a job (a
    # pipeline launcher) that calls back into NGS360 as that user. Unset means no
    # key is minted. Sized to the job definition's timeout: the key is retired
    # when the job ends, and the expiry covers an end that goes unreported.
    # Here rather than on the project type's aws_batch so that it is asked for
    # one action at a time: the other actions run as the backend's own account.
    user_api_key_hours: int | None = Field(default=None, gt=0, le=24 * 7)


class LaunchWorkflow(SQLModel):
    """
    A registered workflow that launches the pipeline.

    The launch hands the workflow's definition and an inputs object to a runner
    job: a batch job whose image knows how to run a workflow in that language.
    The command line and the image then come from the definition itself, and
    the inputs a user can set are the ones the workflow version records.

    Nothing here depends on the workflow's language. The deployment picks the
    runner, and the definition and the input values are passed to it unread.
    """
    # Workflow id, optionally followed by ":<alias>" or ":<version>". Without
    # either, the latest version. A version recorded for the project wins over
    # all three.
    workflow: str
    # Name of the platform whose deployment of that version holds, as its
    # external id, the AWS Batch job definition of the runner for it. A version
    # not deployed there cannot be launched.
    engine: str
    # Inputs the configuration supplies rather than the user: values known from
    # the project, such as its id or where its samplesheet is. Strings are
    # templates, with the variables the commands have. These win over a value
    # for the same input in the request.
    inputs: Dict[str, Any] | None = None


class PlatformConfig(SQLModel):
    """Model for platform-specific configuration (Arvados, SevenBridges, etc)."""
    create_project_command: str | None = None
    launchers: str | List[str] | None = None
    exports: List[Dict[str, str]] | None = None
    export_command: str | None = None
    # Reference models a pipeline can be launched against, each a single
    # {label: reference} pair as in `exports`. The launcher resolves the
    # reference itself, so these must be ones its own configuration knows.
    # Optional: a platform listing none takes the reference as one of the
    # launch workflow's inputs.
    references: List[Dict[str, str]] | None = None
    # Launches the pipeline. Only for a platform with nowhere of its own to
    # start a launcher. Where the launcher is an app the user runs on the
    # platform itself, after create-project has put it in their project, there
    # is nothing to launch from here.
    launch_workflow: LaunchWorkflow | None = None
    # Per-action changes to the project type's aws_batch: the API key a launch
    # asks for, say, or a job queue of its own.
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
    # the launch action. Required for both, except for a launch on a platform
    # that lists no references and takes the reference as a workflow input.
    reference: str | None = None
    # Auto-release flag (only valid for export action)
    auto_release: bool | None = None
    # Values for the inputs of the workflow a launch runs, keyed by input id
    # (only for the launch action)
    inputs: Dict[str, Any] | None = None
