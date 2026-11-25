"""
Models for the Actions API
"""

from enum import Enum
from typing import List, Dict, Any
from pydantic import model_validator
from pydantic_core import PydanticCustomError
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
    A registered workflow that launches a pipeline.

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
    # The size of the runner job for this workflow: vCPUs, and memory in MiB.
    # What the workflow's tools may use comes out of the job's reservation, so
    # a workflow that needs more than the runner's job definition reserves
    # says so here. Either left out keeps the job definition's value.
    vcpus: int | None = Field(default=None, gt=0)
    memory: int | None = Field(default=None, gt=0)


class Launcher(SQLModel):
    """
    One of the launchers a platform runs for a project type, by name.

    A project type can have several: its main pipeline and others that work on
    the same kind of data. The name is what a user chooses and what a launch
    request gives.
    """
    name: str
    # The workflow that launches it. A launcher named without one cannot be
    # launched from here.
    launch_workflow: LaunchWorkflow | None = None


class PlatformConfig(SQLModel):
    """Model for platform-specific configuration (Arvados, SevenBridges, etc)."""
    create_project_command: str | None = None
    # The platform's launchers, in one of two forms. Where a launcher is an app
    # the user runs on the platform itself, after create-project has put it in
    # their project: the ids of those apps, and there is nothing to launch from
    # here. Where a platform has nowhere of its own to start a launcher: named
    # launchers, each with the workflow that launches it.
    launchers: str | List[str | Launcher] | None = None
    exports: List[Dict[str, str]] | None = None
    export_command: str | None = None
    # Per-action changes to the project type's aws_batch: the API key a launch
    # asks for, say, or a job queue of its own.
    aws_batch: Dict[ActionOption, ActionBatchOverride] | None = None

    @model_validator(mode="after")
    def launcher_names_are_unique(self):
        """A launch names its launcher, so two cannot share a name."""
        names = [launcher.name for launcher in self.named_launchers]
        repeated = sorted({name for name in names if names.count(name) > 1})
        if repeated:
            # Not a bare ValueError: the error's context is returned by the
            # endpoint that validates a configuration, and has to be JSON
            raise PydanticCustomError(
                "launcher_names_not_unique",
                "Launcher names must be unique: {names}",
                {"names": ", ".join(repeated)},
            )
        return self

    @property
    def named_launchers(self) -> List[Launcher]:
        """The launchers given by name rather than as an app id."""
        if not isinstance(self.launchers, list):
            return []
        return [launcher for launcher in self.launchers if isinstance(launcher, Launcher)]

    @property
    def launchable(self) -> List[Launcher]:
        """The launchers that can be launched from here: those with a workflow to run."""
        return [launcher for launcher in self.named_launchers if launcher.launch_workflow]


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
    # Label of the export to run (required for the export action, and only
    # used by it)
    reference: str | None = None
    # Auto-release flag (only valid for export action)
    auto_release: bool | None = None
    # Name of the launcher to run (only for the launch action). May be left out
    # where the platform has just one for the project type.
    launcher: str | None = None
    # Values for the inputs of the workflow a launch runs, keyed by input id
    # (only for the launch action)
    inputs: Dict[str, Any] | None = None
