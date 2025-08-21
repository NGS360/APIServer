from typing import Literal, Union
from datetime import datetime
from opensearchpy import OpenSearch, RequestError
from core.logger import logger
from api.search.models import (
   SearchObject, SearchPublic, DynamicSearchResponse
)
from api.project.models import ProjectPublic, Attribute
from api.runs.models import SequencingRunPublic

def _get_searchable_text_fields():
    """
    Dynamically collect all searchable text fields from models that have __searchable__ attribute.
    """
    text_fields = set(['name'])  # Always include 'name' as it's a core text field
    
    try:
        # Import models that have __searchable__ attributes
        from api.runs.models import SequencingRun
        from api.project.models import Project
        
        # Collect searchable fields from each model
        if hasattr(SequencingRun, '__searchable__'):
            text_fields.update(SequencingRun.__searchable__)
        
        if hasattr(Project, '__searchable__'):
            text_fields.update(Project.__searchable__)
            
    except ImportError as e:
        logger.warning(f"Could not import models for searchable fields: {e}")
    
    return list(text_fields)


def _create_model_from_hit(hit: dict, index: str) -> Union[ProjectPublic, SequencingRunPublic]:
    """
    Create the appropriate model instance based on the index type.
    """
    source = hit["_source"]
    
    if index == "projects":
        # Convert attributes from list of dicts to list of Attribute objects
        attributes = []
        if source.get("attributes"):
            attributes = [
                Attribute(key=attr.get("key"), value=attr.get("value"))
                for attr in source["attributes"]
            ]
        
        return ProjectPublic(
            project_id=hit["_id"],  # Use _id as project_id for consistency
            name=source.get("name", ""),
            attributes=attributes
        )
    
    elif index in ["illumina_runs", "runs"]:
        # For sequencing runs, we need to handle the data structure
        # The OpenSearch document might have different field names
        # Parse run_date from various possible formats or use a default
        run_date_str = source.get("run_date")
        if run_date_str:
            try:
                # Try different date formats
                if len(run_date_str) == 10:  # YYYY-MM-DD
                    run_date = datetime.strptime(run_date_str, "%Y-%m-%d").date()
                elif len(run_date_str) == 8:  # YYYYMMDD
                    run_date = datetime.strptime(run_date_str, "%Y%m%d").date()
                else:
                    run_date = datetime.strptime("1970-01-01", "%Y-%m-%d").date()
            except ValueError:
                run_date = datetime.strptime("1970-01-01", "%Y-%m-%d").date()
        else:
            run_date = datetime.strptime("1970-01-01", "%Y-%m-%d").date()
        
        return SequencingRunPublic(
            run_date=run_date,
            machine_id=source.get("machine_id", ""),
            run_number=int(source.get("run_number", 0)) if source.get("run_number") else 0,
            flowcell_id=source.get("flowcell_id", ""),
            experiment_name=source.get("experiment_name"),
            s3_run_folder_path=source.get("s3_run_folder_path"),
            status=source.get("status"),
            run_time=source.get("run_time"),
            barcode=hit["_id"]  # Use _id as barcode for consistency
        )
    
    else:
        # Fallback to SearchObject for unknown indexes
        return SearchObject(
            id=hit["_id"],
            name=source.get("name", ""),
            attributes=source.get("attributes", [])
        )


def add_object_to_index(client: OpenSearch, object: SearchObject, index: str) -> None:
    """
    Add the project to the OpenSearch index.
    """
    # Assuming you have an OpenSearch client set up
    if client is None:
        logger.warning("OpenSearch client is not available.")
        return

    # Prepare the document to index
    doc = {
        "id": str(object.id),
        "name": object.name,
        "attributes": [
            {"key": attr.key, "value": attr.value} for attr in object.attributes or []
        ]
    }

    # Index the document
    client.index(index=index, id=str(object.id), body=doc)
    client.indices.refresh(index=index)


def _get_response_key_for_index(index: str) -> str:
    """
    Determine the appropriate response key based on the index name.
    Maps index names to their corresponding response keys.
    """
    index_to_key_mapping = {
        'projects': 'projects',
        'illumina_runs': 'illumina_runs',
        'runs': 'runs',
        # Add more mappings as needed
    }
    
    # Return the mapped key, or fallback to 'data' for unknown indexes
    return index_to_key_mapping.get(index, 'data')


def search(
    client: OpenSearch,
    index: str,
    query: str,
    page: int,
    per_page: int,
    sort_by: str | None,
    sort_order: Literal['asc', 'desc'] | None
) -> DynamicSearchResponse:
    """
    Perform a search with pagination and sorting.
    """
    logger.debug(f"Search called with index='{index}', query='{query}'")
    
    if not client:
        logger.error("OpenSearch client is not available.")
        return SearchPublic()

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

    # Add sorting if specified
    if sort_by and sort_order:
        # Get text fields that need .keyword suffix for sorting
        text_fields = _get_searchable_text_fields()
        
        # Use .keyword suffix for text fields, otherwise use field as-is
        sort_field = f"{sort_by}.keyword" if sort_by in text_fields else sort_by
        
        search_body["sort"] = [
            {sort_field: {"order": sort_order}}
        ]

    try:
        response = client.search(index=index, body=search_body)
    except RequestError as e:
        # If sorting fails, try without .keyword suffix
        if sort_by and sort_order and "Text fields are not optimised" in str(e):
            logger.warning(f"Sorting failed with .keyword suffix, retrying with original field: {sort_by}")
            search_body["sort"] = [
                {sort_by: {"order": sort_order}}
            ]
            try:
                response = client.search(index=index, body=search_body)
            except RequestError as e2:
                # If it still fails, remove sorting and log the error
                logger.error(f"Sorting failed for field '{sort_by}': {str(e2)}")
                search_body.pop("sort", None)
                response = client.search(index=index, body=search_body)
        else:
            # Re-raise if it's a different error
            raise e

    # Create appropriate model instances based on index
    items = [
        _create_model_from_hit(hit, index)
        for hit in response["hits"]["hits"]
    ]
    
    # Log search response structure for diagnosis
    logger.debug(f"Search endpoint created {len(items)} {type(items[0]).__name__ if items else 'No'} items for index '{index}'")

    total_items = response["hits"]["total"]["value"]
    
    # Calculate pagination metadata (same logic as projects service)
    total_pages = (total_items + per_page - 1) // per_page  # Ceiling division

    # Determine the appropriate response key based on the index
    response_key = _get_response_key_for_index(index)
    
    # Create the dynamic response
    result = DynamicSearchResponse(
        total_items=total_items,
        total_pages=total_pages,
        current_page=page,
        per_page=per_page,
        has_next=page < total_pages,
        has_prev=page > 1
    )
    
    # Dynamically set the results under the appropriate key
    setattr(result, response_key, items)
    
    logger.debug(f"Returning search results with '{response_key}' key for index '{index}'. Items count: {len(items)}")
    
    return result
