from opensearchpy import OpenSearch
from core.logger import logger
from api.search.models import (
   SearchObject, SearchPublic, SearchAttribute
)
from sqlmodel import Session
# Removed circular import - will use lazy import in reindex function

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
    page: int = 1,
    per_page: int = 20,
) -> SearchPublic:
    """
    Perform a search with pagination and sorting.
    """
    if not client:
        logger.error("OpenSearch client is not available.")
        return SearchPublic(items=[], total=0, page=page, per_page=per_page)

    # Construct the search query
    search_body = {
        "query": {
            "query_string": {
                'query': query,
                "fields": ['*'],
            }
        },
        "from": (page - 1) * per_page,
        "size": per_page
    }

    response = client.search(index=index, body=search_body)

    items = [
        SearchObject(
            id=hit["_id"],
            name=hit["_source"].get("name", ""),
            attributes=hit["_source"].get("attributes", [])
        ) for hit in response["hits"]["hits"]
    ]

    total = response["hits"]["total"]["value"]

    return SearchPublic(items=items, total=total, page=page, per_page=per_page)

def reindex(session: Session, client: OpenSearch, index: str) -> None:
    """
    Reindex the search index.
    """
    if not client:
        logger.error("OpenSearch client is not available.")
        return

    # Clear the existing index
    if client.indices.exists(index=index):
        client.indices.delete(index=index)

    # Create a new index
    client.indices.create(index=index, ignore=400)

    # Use lazy import to avoid circular dependency
    from api.project.services import get_projects
    
    # Fetch all projects using pagination
    page = 1
    per_page = 1000  # Reasonable page size for reindexing
    total_indexed = 0

    while True:
        logger.info(f"Fetching projects page {page} (per_page={per_page})")
        
        # Call get_projects with proper parameters
        projects_response = get_projects(
            session=session,
            page=page,
            per_page=per_page,
            sort_by="id",
            sort_order="asc"
        )
        
        # If no projects on this page, we're done
        if not projects_response.data:
            break
            
        # Index all projects from this page
        for project in projects_response.data:
            logger.debug(f"Reindexing project {project.project_id}")
            search_attributes = [
                SearchAttribute(key=attr.key, value=attr.value)
                for attr in project.attributes or []
            ]
            search_object = SearchObject(id=project.project_id, name=project.name, attributes=search_attributes)
            add_object_to_index(client, search_object, index)
            total_indexed += 1
        
        # Check if we've reached the last page
        if not projects_response.has_next:
            break
            
        page += 1
    client.indices.refresh(index=index)
    logger.info(f"Reindexing completed. Total projects indexed: {total_indexed}")
