"""
Services for managing sequencing runs.
"""
import json
import yaml
import boto3
import botocore
from typing import List, Literal, Dict, Any
from sqlmodel import select, Session, func
from pydantic import PositiveInt
from opensearchpy import OpenSearch
from fastapi import HTTPException, Response, status, UploadFile
from smart_open import open as smart_open
from botocore.exceptions import NoCredentialsError, ClientError

from jinja2.sandbox import SandboxedEnvironment

from sample_sheet import SampleSheet as IlluminaSampleSheet

from core.utils import define_search_body
from core.logger import logger

from api.runs.models import (
    DemuxWorkflowConfig,
    DemuxWorkflowSubmitBody,
    IlluminaMetricsResponseModel,
    IlluminaSampleSheetResponseModel,
    RunStatus,
    SequencingRun,
    SequencingRunCreate,
    SequencingRunPublic,
    SequencingRunsPublic,
)
from api.search.services import add_object_to_index, delete_index
from api.search.models import (
    SearchDocument,
)
from api.settings.services import get_setting_value


def add_run(
    session: Session,
    sequencingrun_in: SequencingRunCreate,
    opensearch_client: OpenSearch = None,
) -> SequencingRun:
    """Add a new sequencing run to the database and index it in OpenSearch."""
    # Create the SequencingRun instance
    run = SequencingRun(**sequencingrun_in.model_dump())

    # Add to the database
    session.add(run)
    session.commit()
    session.refresh(run)

    # Index in OpenSearch if client is provided
    if opensearch_client:
        search_doc = SearchDocument(id=run.barcode, body=run)
        add_object_to_index(opensearch_client, search_doc, "illumina_runs")

    return run


def get_run(
    session: Session,
    run_barcode: str,
) -> SequencingRunPublic:
    """
    Retrieve a sequencing run from the database.
    """
    (run_date, run_time, machine_id, run_number, flowcell_id) = (
        SequencingRun.parse_barcode(run_barcode)
    )
    run = session.exec(
        select(SequencingRun).where(
            SequencingRun.run_date == run_date,
            SequencingRun.machine_id == machine_id,
            SequencingRun.run_number == run_number,
            SequencingRun.flowcell_id == flowcell_id,
        )
    ).one_or_none()

    if run is None:
        return None

    return run


def get_runs(
    *,
    session: Session,
    page: PositiveInt,
    per_page: PositiveInt,
    sort_by: str,
    sort_order: Literal["asc", "desc"],
) -> List[SequencingRun]:
    """
    Returns all sequencing runs from the database along
    with pagination information.
    """
    # Get total run count
    total_count = session.exec(select(func.count()).select_from(SequencingRun)).one()

    # Compute total pages
    total_pages = (total_count + per_page - 1) // per_page  # Ceiling division

    # Determine sort field and direction
    # Handle computed fields that can't be sorted directly
    if sort_by == "barcode":
        # For barcode sorting, use run_date as primary sort field since barcode starts with date
        sort_field = SequencingRun.run_date
    else:
        # Get the actual database column, fallback to id if field doesn't exist
        sort_field = getattr(SequencingRun, sort_by, SequencingRun.id)
        # Ensure we got a column, not a property
        if not hasattr(sort_field, 'asc'):
            sort_field = SequencingRun.id

    sort_direction = sort_field.asc() if sort_order == "asc" else sort_field.desc()

    # Get run selection
    runs = session.exec(
        select(SequencingRun)
        .order_by(sort_direction)
        .limit(per_page)
        .offset((page - 1) * per_page)
    ).all()

    # Map to public run
    public_runs = [
        SequencingRunPublic(
            id=run.id,
            run_date=run.run_date,
            machine_id=run.machine_id,
            run_number=run.run_number,
            flowcell_id=run.flowcell_id,
            experiment_name=run.experiment_name,
            run_folder_uri=run.run_folder_uri,
            status=run.status,
            run_time=run.run_time,
            barcode=run.barcode,
        )
        for run in runs
    ]

    return SequencingRunsPublic(
        data=public_runs,
        total_items=total_count,
        total_pages=total_pages,
        current_page=page,
        per_page=per_page,
        has_next=page < total_pages,
        has_prev=page > 1,
    )


def search_runs(
    session: Session,
    client: OpenSearch,
    query: str,
    page: int,
    per_page: int,
    sort_by: str | None = "barcode",
    sort_order: Literal["asc", "desc"] | None = "asc",
) -> SequencingRunsPublic:
    """
    Search for runs
    """
    # Construct the search query
    search_body = define_search_body(query, page, per_page, sort_by, sort_order)

    try:

        response = client.search(index="illumina_runs", body=search_body)

        # Total Items and Pages needs to be calculated from OpenSearch response
        # or else pagination info will be incorrect for clients
        total_items = response["hits"]["total"]["value"]
        total_pages = (total_items + per_page - 1) // per_page  # Ceiling division

        # Unpack search results into ProjectPublic model
        results = []
        for hit in response["hits"]["hits"]:
            source = hit["_source"]
            run = get_run(session=session, run_barcode=source.get("barcode"))
            if run:
                results.append(SequencingRunPublic.model_validate(run))

        return SequencingRunsPublic(
            data=results,
            total_items=total_items,
            total_pages=total_pages,
            current_page=page,
            per_page=per_page,
            has_next=page < total_pages,
            has_prev=page > 1,
        )

    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e)) from e


def reindex_runs(
    session: Session,
    client: OpenSearch
):
    """
    Index all runs in database with OpenSearch
    """
    delete_index(client, "illumina_runs")
    runs = session.exec(
        select(SequencingRun)
    ).all()
    for run in runs:
        search_doc = SearchDocument(id=run.barcode, body=run)
        add_object_to_index(client, search_doc, "illumina_runs")


def get_run_samplesheet(session: Session, run_barcode: str):
    """
    Retrieve the samplesheet for a given sequencing run.
    :return: A dictionary representing the samplesheet in JSON format.
    """
    sample_sheet_json = {
        'Summary': {},
        'Header': {},
        'Reads': [],
        'Settings': {},
        'DataCols': [],
        'Data': []
    }
    run = get_run(session=session, run_barcode=run_barcode)
    if run is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Run with barcode {run_barcode} not found"
        )

    # Convert run data to strings for the response model, excluding the database ID
    run_dict = run.to_dict()
    summary_dict = {}
    for key, value in run_dict.items():
        if key == 'id':  # Skip the database ID field
            continue
        if value is None:
            summary_dict[key] = ""
        else:
            summary_dict[key] = str(value)
    sample_sheet_json['Summary'] = summary_dict

    # Check if the samplesheet exists in URI path
    if run.run_folder_uri:
        sample_sheet_path = f"{run.run_folder_uri}/SampleSheet.csv"
        try:
            sample_sheet = IlluminaSampleSheet(sample_sheet_path)
            sample_sheet = sample_sheet.to_json()
            sample_sheet = json.loads(sample_sheet)
            sample_sheet_json['Header'] = sample_sheet['Header']
            sample_sheet_json['Reads'] = sample_sheet['Reads']
            sample_sheet_json['Settings'] = sample_sheet['Settings']
            if sample_sheet['Data']:
                sample_sheet_json['DataCols'] = list(sample_sheet['Data'][0].keys())
            sample_sheet_json['Data'] = sample_sheet['Data']
        except FileNotFoundError:
            # Samplesheet not found, signal with 204 response
            return Response(
                status_code=status.HTTP_204_NO_CONTENT,
            )
        except OSError as e:
            # Need to catch specific error for S3
            # where object doesn't exist and respond with 204
            if e.backend_error.response['Error']['Code'] == 'NoSuchKey':
                return Response(
                    status_code=status.HTTP_204_NO_CONTENT,
                )
            # Need to catch specific error for S3
            # where access is denied and respond with 403
            if e.backend_error.response['Error']['Code'] == 'AccessDenied':
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Access denied when trying to read samplesheet."
                ) from e
        except NoCredentialsError as e:
            error_type = f"{type(e).__module__}.{type(e).__name__}"
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Error accessing samplesheet: {error_type}: {str(e)}"
            ) from e

    return IlluminaSampleSheetResponseModel(**sample_sheet_json)


def get_run_metrics(session: Session, run_barcode: str) -> dict:
    """
    Retrieve demultiplexing metrics for a specific run.
    :return: A dictionary containing the demultiplexing metrics.
    """
    run = get_run(session=session, run_barcode=run_barcode)
    if run is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Run with barcode {run_barcode} not found"
        )

    # Check if the metrics file exists in S3
    metrics = {}
    if run.run_folder_uri:
        metrics_path = f"{run.run_folder_uri}/Stats/Stats.json"
        try:
            with smart_open(metrics_path, 'r') as f:
                metrics = json.load(f)

        except FileNotFoundError:
            # Samplesheet not found, signal with 204 response
            return Response(
                status_code=status.HTTP_204_NO_CONTENT,
            )
        except OSError as e:
            # Need to catch specific error for S3
            # where object doesn't exist and respond with 204
            if e.backend_error.response['Error']['Code'] == 'NoSuchKey':
                return Response(
                    status_code=status.HTTP_204_NO_CONTENT,
                )
            # Need to catch specific error for S3
            # where access is denied and respond with 403
            if e.backend_error.response['Error']['Code'] == 'AccessDenied':
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Access denied when trying to read samplesheet."
                ) from e
        except NoCredentialsError as e:
            error_type = f"{type(e).__module__}.{type(e).__name__}"
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Error accessing samplesheet: {error_type}: {str(e)}"
            ) from e
    return IlluminaMetricsResponseModel(**metrics)


def update_run(session: Session, run_barcode: str, run_status: RunStatus) -> SequencingRunPublic:
    """
    Update the status of a specific run.
    """
    run = get_run(session=session, run_barcode=run_barcode)
    if run is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Run with barcode {run_barcode} not found"
        )

    run.status = run_status
    session.add(run)
    session.commit()
    session.refresh(run)

    return SequencingRunPublic(
        id=run.id,
        run_date=run.run_date,
        machine_id=run.machine_id,
        run_number=run.run_number,
        flowcell_id=run.flowcell_id,
        experiment_name=run.experiment_name,
        run_folder_uri=run.run_folder_uri,
        status=run.status,
        run_time=run.run_time,
        barcode=run.barcode,
    )


def upload_samplesheet(
    session: Session, run_barcode: str, file: UploadFile
) -> IlluminaSampleSheetResponseModel:
    """
    Upload a new samplesheet for a specific run.
    """
    run = get_run(session=session, run_barcode=run_barcode)
    if run is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Run with barcode {run_barcode} not found"
        )

    if not run.run_folder_uri:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Run folder URI is not set. Cannot upload samplesheet."
        )

    # Define the path to upload the samplesheet
    samplesheet_path = f"{run.run_folder_uri}/SampleSheet.csv"

    try:
        # Upload the file using smart_open
        with smart_open(samplesheet_path, 'wb') as out_file:
            content = file.file.read()
            out_file.write(content)
    except NoCredentialsError as e:
        error_type = f"{type(e).__module__}.{type(e).__name__}"
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error uploading samplesheet: {error_type}: {str(e)}"
        ) from e

    # After successful upload, read back the samplesheet to return its content
    try:
        sample_sheet = IlluminaSampleSheet(samplesheet_path)
        sample_sheet = sample_sheet.to_json()
        sample_sheet = json.loads(sample_sheet)
        sample_sheet_json = {
            'Summary': sample_sheet.get('Summary', {}),
            'Header': sample_sheet.get('Header', {}),
            'Reads': sample_sheet.get('Reads', []),
            'Settings': sample_sheet.get('Settings', {}),
            'DataCols': list(sample_sheet['Data'][0].keys()) if sample_sheet.get('Data') else [],
            'Data': sample_sheet.get('Data', [])
        }
        return IlluminaSampleSheetResponseModel(**sample_sheet_json)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error reading back uploaded samplesheet: {type(e).__name__}: {str(e)}"
        ) from e

###############################################################################
# Demultiplex Workflows
###############################################################################


def _get_demux_workflow_configs_s3_location(session: Session) -> tuple[str, str]:
    """
    Get the S3 bucket and prefix for demultiplex workflow configurations.

    Args:
        session: Database session

    Returns:
        Tuple of (bucket, prefix) where prefix includes the full path with subfolders
    """
    workflow_configs_uri = get_setting_value(
        session,
        "DEMUX_WORKFLOW_CONFIGS_BUCKET_URI"
    )

    # Ensure URI ends with /
    if not workflow_configs_uri.endswith("/"):
        workflow_configs_uri += "/"

    # Parse S3 URI to get bucket and prefix
    s3_path = workflow_configs_uri.replace("s3://", "")
    bucket = s3_path.split("/")[0]
    prefix = "/".join(s3_path.split("/")[1:])

    return bucket, prefix


def list_demux_workflow_configs(session: Session, s3_client=None) -> list[str]:
    """
    List available demultiplex workflow configuration files from S3.

    Args:
        session: Database session
        s3_client: Optional boto3 S3 client

    Returns:
        List of demultiplex workflow configuration filenames (without .yaml extension)
    """
    bucket, prefix = _get_demux_workflow_configs_s3_location(session)

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
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=(
                f"Unexpected error listing tool configs: {str(exc)}"
            ),
        ) from exc


def get_demux_workflow_config(
    session: Session, workflow_id: str, s3_client=None
) -> DemuxWorkflowConfig:
    """
    Retrieve a specific tool configuration from S3.

    Args:
        session: Database session
        workflow_id: The workflow identifier (filename without extension)
        s3_client: Optional boto3 S3 client

    Returns:
        DemuxWorkflowConfig object
    """
    bucket, prefix = _get_demux_workflow_configs_s3_location(session)

    try:
        if s3_client is None:
            s3_client = boto3.client("s3")

        # Try both .yaml and .yml extensions
        key = None
        for ext in [".yaml", ".yml"]:
            potential_key = f"{prefix}{workflow_id}{ext}"
            try:
                # Try to get the object directly instead of using head_object
                response = s3_client.get_object(Bucket=bucket, Key=potential_key)
                key = potential_key
                yaml_content = response["Body"].read().decode("utf-8")
                break
            except ClientError as e:
                error_code = e.response["Error"]["Code"]
                if error_code in ["NoSuchKey", "404"]:
                    continue  # Try next extension
                else:
                    raise  # Re-raise other errors

        if key is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Demultiplex workflow config '{workflow_id}' not found",
            )

        # Parse YAML
        config_data = yaml.safe_load(yaml_content)

        # Validate and return as DemuxWorkflowConfig model
        return DemuxWorkflowConfig(**config_data)

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
        elif error_code == "NoSuchKey":
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Demultiplex workflow config '{workflow_id}' not found",
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
    except yaml.YAMLError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Invalid YAML format in demultiplex workflow config: {str(exc)}",
        ) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Unexpected error retrieving demultiplex workflow config: {str(exc)}",
        ) from exc


def interpolate(str_in: str, inputs: Dict[str, Any]) -> str:
    '''
    Take an input str, and substitute expressions containing variables with
    their actual values provided in inputs. Uses Jinja2 SandboxedEnvironment
    to prevent code execution vulnerabilities.

    :param str_in: String to be interpolated
    :param inputs: Dictionary of tool inputs (key-value pairs with demultiplex workflow inputs and
                   defaults pre-populated)
    :return: String containing substitutions
    '''
    env = SandboxedEnvironment()
    template = env.from_string(str_in)
    str_out = template.render(inputs).strip()
    return str_out


def _submit_job(
    session: Session,
    job_name: str,
    container_overrides: Dict[str, Any],
    job_def: str,
    job_queue: str
) -> dict:
    """
    Submit a job to AWS Batch, and return the job id.

    Args:
        session: Database session for retrieving AWS settings
        job_name: Name of the job to submit
        container_overrides: Container configuration overrides
        job_def: Job definition name
        job_queue: Job queue name
    """
    logger.info(
        f"Submitting job '{job_name}' to AWS Batch queue '{job_queue}' "
        f"with definition '{job_def}'"
    )
    logger.info(f"Container overrides: {container_overrides}")

    aws_region = get_setting_value(session, "AWS_REGION") or "us-east-1"

    try:
        batch_client = boto3.client("batch", region_name=aws_region)
        response = batch_client.submit_job(
            jobName=job_name,
            jobQueue=job_queue,
            jobDefinition=job_def,
            containerOverrides=container_overrides,
        )
    except botocore.exceptions.ClientError as err:
        logger.error(f"Failed to submit job to AWS Batch: {err}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to submit job to AWS Batch: {err}",
        ) from err

    return response


def submit_job(session: Session, workflow_body: DemuxWorkflowSubmitBody, s3_client=None) -> dict:
    """
    Submit an AWS Batch job for the specified demultiplex workflow.

    Args:
        session: Database session
        workflow_body: The demultiplex workflow execution request containing workflow_id,
                   run_barcode, and inputs
        s3_client: Optional boto3 S3 client
    Returns:
        A dictionary containing job submission details.
    """
    tool_config = get_demux_workflow_config(
        session=session, workflow_id=workflow_body.workflow_id, s3_client=s3_client
    )

    # Interpolate inputs with aws_batch schema definition
    if not tool_config.aws_batch:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Demultiplex workflow '{workflow_body.workflow_id}' is not configured for "
                f"AWS Batch execution."
            ),
        )

    job_name = interpolate(tool_config.aws_batch.job_name, workflow_body.inputs)
    command = interpolate(tool_config.aws_batch.command, workflow_body.inputs)
    container_overrides = {
        "command": command.split(),
        "environment": [
            {
                "name": env.name,
                "value": interpolate(env.value, workflow_body.inputs)
            }
            for env in (tool_config.aws_batch.environment or [])
        ],
    }

    # Submit the job to AWS Batch
    response = _submit_job(
        session=session,
        job_name=job_name,
        container_overrides=container_overrides,
        job_def=tool_config.aws_batch.job_definition,
        job_queue=tool_config.aws_batch.job_queue,
    )

    if 'jobId' in response:
        response['jobCommand'] = command

    return response
