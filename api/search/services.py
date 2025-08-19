from typing import Literal
from opensearchpy import OpenSearch, RequestError
from core.logger import logger
from api.search.models import (
   SearchObject, SearchPublic
)

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


def search(
    client: OpenSearch,
    index: str,
    query: str,
    page: int,
    per_page: int,
    sort_by: str | None,
    sort_order: Literal['asc', 'desc'] | None
) -> SearchPublic:
    """
    Perform a search with pagination and sorting.
    """
    if not client:
        logger.error("OpenSearch client is not available.")
        return SearchPublic(items=[], total=0, page=page, per_page=per_page)

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

    items = [
        SearchObject(
            id=hit["_id"],
            name=hit["_source"].get("name", ""),
            attributes=hit["_source"].get("attributes", [])
        ) for hit in response["hits"]["hits"]
    ]

    total = response["hits"]["total"]["value"]

    return SearchPublic(items=items, total=total, page=page, per_page=per_page)
