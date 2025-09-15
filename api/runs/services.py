"""
Services for managing sequencing runs.
"""
import json
from typing import List, Literal
from sqlmodel import select, Session, func
from pydantic import PositiveInt
from opensearchpy import OpenSearch
from fastapi import HTTPException, Response, status
from smart_open import open as smart_open
from botocore.exceptions import NoCredentialsError

from sample_sheet import SampleSheet as IlluminaSampleSheet

from core.utils import define_search_body

from api.runs.models import (
    IlluminaMetricsResponseModel,
    IlluminaSampleSheetResponseModel,
    SequencingRun,
    SequencingRunCreate,
    SequencingRunPublic,
    SequencingRunsPublic,
)
from api.search.services import add_object_to_index
from api.search.models import (
    SearchDocument,
)


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
    sort_field = getattr(SequencingRun, sort_by, SequencingRun.id)
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
        total_items = response["hits"]["total"]["value"]
        total_pages = (total_items + per_page - 1) // per_page  # Ceiling division

        # Unpack search results into ProjectPublic model
        results = []
        for hit in response["hits"]["hits"]:
            source = hit["_source"]
            run = get_run(session=session, run_barcode=source.get("barcode"))
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
        return sample_sheet_json

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
        except NoCredentialsError:
            # Throw a more helpful error if AWS credentials are missing
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Configure AWS credentials to access your s3 bucket."
            )

    return IlluminaSampleSheetResponseModel(**sample_sheet_json)


def get_run_metrics(session: Session, run_barcode: str) -> dict:
    """
    Retrieve demultiplexing metrics for a specific run.
    :return: A dictionary containing the demultiplexing metrics.
    """
    run = get_run(session=session, run_barcode=run_barcode)
    if run is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Run with barcode {run_barcode} does not exist."
        )

    # Check if the metrics file exists in S3
    if run.run_folder_uri:
        metrics_path = f"{run.run_folder_uri}/Stats/Stats.json"
        try:
            with smart_open(metrics_path, 'r') as f:
                metrics = json.load(f)
            return metrics
        except FileNotFoundError:
            # Metrics file not found, raise not found error
            return Response(
                status_code=status.HTTP_204_NO_CONTENT,
            )
    return IlluminaMetricsResponseModel(**metrics)
