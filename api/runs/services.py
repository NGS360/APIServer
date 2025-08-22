from sqlmodel import select, Session, func
from typing import List, Literal
from pydantic import PositiveInt
from sqlalchemy import asc, desc
from opensearchpy import OpenSearch

from api.runs.models import (
    SequencingRun, 
    SequencingRunCreate,
    SequencingRunPublic, 
    SequencingRunsPublic
)
from api.search.services import add_object_to_index
from api.search.models import (
    SearchDocument,
)

def add_run(
    session: Session,
    sequencingrun_in: SequencingRunCreate,
    opensearch_client: OpenSearch = None
) -> SequencingRun:
    """ Add a new sequencing run to the database and index it in OpenSearch.
    """
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
    (run_date, run_time, machine_id, run_number, flowcell_id) = SequencingRun.parse_barcode(run_barcode)
    run = session.exec(
        select(SequencingRun).where(
            SequencingRun.run_date == run_date,
            SequencingRun.machine_id == machine_id,
            SequencingRun.run_number == run_number,
            SequencingRun.flowcell_id == flowcell_id
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
      sort_order: Literal['asc', 'desc']
   ) -> List[SequencingRun]:
    """
    Returns all sequencing runs from the database along
    with pagination information.
    """
    # Get total run count
    total_count = session.exec(
        select(func.count()).select_from(SequencingRun)
    ).one()

    # Compute total pages
    total_pages = (total_count + per_page - 1) // per_page  # Ceiling division

    # Determine sort field and direction
    sort_field = getattr(SequencingRun, sort_by, SequencingRun.id)
    sort_direction = sort_field.asc() if sort_order == 'asc' else sort_field.desc()

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
            s3_run_folder_path=run.s3_run_folder_path,
            status=run.status,
            run_time=run.run_time,
            barcode=run.barcode
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
        has_prev=page > 1
    )
