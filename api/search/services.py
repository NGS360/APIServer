from typing import Literal
from opensearchpy import OpenSearch
from core.logger import logger
from core.deps import SessionDep
from api.search.models import (
   SearchObject, SearchPublic
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

def search(
    index: str,
    page: int = 1,
    per_page: int = 20,
    sort_by: str = 'id',
    sort_order: Literal['asc', 'desc'] = 'asc'
) -> SearchPublic:
    """
    Perform a search with pagination and sorting.
    """
    from core.opensearch import client  # Import the global client
    
    if not client:
        logger.error("OpenSearch client is not available.")
        return SearchPublic(items=[], total=0, page=page, per_page=per_page)

    # Construct the search query
    query = {
        "query": {
            "match_all": {}
        },
        "sort": [
            {sort_by: {"order": sort_order}}
        ],
        "from": (page - 1) * per_page,
        "size": per_page
    }

    response = client.search(index=index, body=query)

    items = [
        SearchObject(
            id=hit["_id"],
            name=hit["_source"].get("name", ""),
            attributes=hit["_source"].get("attributes", [])
        ) for hit in response["hits"]["hits"]
    ]

    total = response["hits"]["total"]["value"]

    return SearchPublic(items=items, total=total, page=page, per_page=per_page)
