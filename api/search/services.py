from typing import Literal, Union
from datetime import datetime
from opensearchpy import OpenSearch, RequestError
from sqlmodel import Session, select
from core.logger import logger
from core.deps import get_db
from core.opensearch import INDEXES
from api.search.models import (
    SearchDocument,
    SearchResponse
)
from api.project.models import Project, ProjectPublic, Attribute
from api.runs.models import SequencingRun, SequencingRunPublic

def add_object_to_index(client: OpenSearch, document: SearchDocument, index: str) -> None:
    """
    Add a document (that can be converted to JSON) to the OpenSearch index.
    """
    # Assuming you have an OpenSearch client set up
    if client is None:
        logger.warning("OpenSearch client is not available.")
        return

    payload = {}
    for field in document.body.__searchable__:
        value = getattr(document.body, field)
        if value:
            payload[field] = getattr(document.body, field)

    # Index the document
    client.index(index=index, id=str(document.id), body=payload)
    client.indices.refresh(index=index)


def _create_model_from_hit(hit, index: str, session: Session) -> Union[ProjectPublic, SequencingRunPublic]:
    """
    Create a SQLModel object (ProjectPublic, SequencingRunPublic) from the hit['_id'] field based on what index is.
    
    Args:
        hit: OpenSearch hit object containing _id and _source
        index: The index name ('projects' or 'illumina_runs')
        session: Database session for fetching data
        
    Returns:
        ProjectPublic or SequencingRunPublic object based on the index
    """
    hit_id = hit['_id']
    
    if index == 'projects':
        # For projects, the _id is the project_id
        project = session.exec(
            select(Project).where(Project.project_id == hit_id)
        ).first()
        
        if not project:
            logger.warning(f"Project with project_id {hit_id} not found in database")
            return None
            
        return ProjectPublic(
            project_id=project.project_id,
            name=project.name,
            attributes=[
                Attribute(key=attr.key, value=attr.value)
                for attr in project.attributes or []
            ]
        )
    elif index == 'illumina_runs':
        # For runs, the _id is the barcode
        # Parse the barcode to get the individual components
        (run_date, run_time, machine_id, run_number, flowcell_id) = SequencingRun.parse_barcode(hit_id)
        
        if run_date is None:
            logger.warning(f"Invalid barcode format: {hit_id}")
            return None
            
        run = session.exec(
            select(SequencingRun).where(
                SequencingRun.run_date == run_date,
                SequencingRun.machine_id == machine_id,
                SequencingRun.run_number == run_number,
                SequencingRun.flowcell_id == flowcell_id
            )
        ).first()
        
        if run is None:
            logger.warning(f"Run with barcode {hit_id} not found in database")
            return None
            
        return SequencingRunPublic(
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
    else:
        logger.error(f"Unknown index: {index}")
        return None

def search(
    client: OpenSearch,
    index: str,
    query: str,
    page: int,
    per_page: int,
    sort_by: str | None,
    sort_order: Literal['asc', 'desc'] | None,
    session: Session
) -> SearchResponse:
    """
    Perform a search with pagination and sorting.
    """
    if not client:
        logger.error("OpenSearch client is not available.")
        return SearchResponse()
    if index not in INDEXES:
        logger.error("Uknown index %s", index)
        return SearchResponse()

    # Construct the search query
    search_list = query.split(" ")
    formatted_list = ["(*{}*)".format(token) for token in search_list]
    search_str = " AND ".join(formatted_list)

    search_body = {
        "query": {
            "query_string": {
                'query': search_str,
                "fields": ['*'],
            }
        },
        "from": (page - 1) * per_page,
        "size": per_page
    }

    response = client.search(index=index, body=search_body)

    total_items = response["hits"]["total"]["value"]
    total_pages = (total_items + per_page - 1) // per_page  # Ceiling division

    # Create appropriate model instances based on index
    items = []
    for hit in response["hits"]["hits"]:
        item = _create_model_from_hit(hit, index, session)
        if item is not None:  # Skip None results (e.g., when data not found in DB)
            items.append(item)

    # Create the dynamic response
    result = SearchResponse(
        total_items=total_items,
        total_pages=total_pages,
        current_page=page,
        per_page=per_page,
        has_next=page < total_pages,
        has_prev=page > 1
    )
    # Dynamically set the results under the appropriate key
    setattr(result, index, items)

    return result
