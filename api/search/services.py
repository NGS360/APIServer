from typing import Literal, Union, Dict, Type, Callable
from datetime import datetime
from opensearchpy import OpenSearch, RequestError
from sqlmodel import Session, select
from core.logger import logger
from core.deps import get_db
from core.opensearch import INDEXES
from api.search.models import (
    SearchDocument,
    SearchResponse,
    ProjectSearchResponse,
    RunSearchResponse,
    GenericSearchResponse,
    BaseSearchResponse
)
from api.project.models import ProjectPublic
from api.runs.models import SequencingRunPublic

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


# Index configuration mapping
INDEX_CONFIG = {
    'projects': {
        'response_class': ProjectSearchResponse,
        'field_name': 'projects',
        'model_creator': lambda hit_id, session: _get_project_by_id(hit_id, session)
    },
    'illumina_runs': {
        'response_class': RunSearchResponse,
        'field_name': 'illumina_runs',
        'model_creator': lambda hit_id, session: _get_run_by_barcode(hit_id, session)
    }
}

def _get_project_by_id(project_id: str, session: Session) -> ProjectPublic:
    """Get project by ID"""
    from api.project.services import get_project_by_project_id
    return get_project_by_project_id(session=session, project_id=project_id)

def _get_run_by_barcode(run_barcode: str, session: Session) -> SequencingRunPublic:
    """Get run by barcode"""
    from api.runs.services import get_run
    return get_run(session=session, run_barcode=run_barcode)

def _create_model_from_hit(hit, index: str, session: Session) -> Union[ProjectPublic, SequencingRunPublic]:
    """
    Create a SQLModel object from the hit['_id'] field based on what index is.
    
    Args:
        hit: OpenSearch hit object containing _id and _source
        index: The index name ('projects' or 'illumina_runs')
        session: Database session for fetching data
        
    Returns:
        ProjectPublic or SequencingRunPublic object based on the index
    """
    hit_id = hit['_id']
    
    if index in INDEX_CONFIG:
        return INDEX_CONFIG[index]['model_creator'](hit_id, session)
    else:
        logger.error(f"Unknown index: {index}")
        return None

def _get_empty_response(index: str) -> SearchResponse:
    """Get appropriate empty response based on index"""
    if index in INDEX_CONFIG:
        return INDEX_CONFIG[index]['response_class']()
    return GenericSearchResponse()

def _create_response(index: str, items: list, base_params: dict) -> SearchResponse:
    """Create appropriate response model based on index"""
    if index in INDEX_CONFIG:
        config = INDEX_CONFIG[index]
        field_data = {config['field_name']: items}
        return config['response_class'](**field_data, **base_params)
    else:
        # Convert items to SearchDocument for generic response
        search_docs = []
        for item in items:
            search_docs.append(SearchDocument(id=str(item.id), body=item))
        return GenericSearchResponse(data=search_docs, **base_params)

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
    # Early returns for error conditions
    if not client:
        logger.error("OpenSearch client is not available.")
        return _get_empty_response(index)
            
    if index not in INDEXES:
        logger.error("Unknown index %s", index)
        return _get_empty_response(index)

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

    # Create the appropriate response model based on index
    base_params = {
        "total_items": total_items,
        "total_pages": total_pages,
        "current_page": page,
        "per_page": per_page,
        "has_next": page < total_pages,
        "has_prev": page > 1
    }
    
    return _create_response(index, items, base_params)
