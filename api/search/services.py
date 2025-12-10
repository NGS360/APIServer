"""
Search-related services
"""
from opensearchpy import OpenSearch
from sqlmodel import Session

from core.logger import logger

from api.search.models import (
    SearchDocument,
    SearchResponse,
)


def add_object_to_index(
    client: OpenSearch, document: SearchDocument, index: str
) -> None:
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


def delete_index(client: OpenSearch, index: str) -> None:
    """
    Delete an OpenSearch index.
    """
    if client is None:
        logger.warning("OpenSearch client is not available.")
        return

    client.indices.delete(index=index, ignore=[400, 404])


def search(
    client: OpenSearch, session: Session, query: str, n_results: int = 5
) -> SearchResponse:
    """
    Unified search across indices
    """
    from api.project.services import search_projects
    from api.runs.services import search_runs

    args = {
        "session": session,
        "client": client,
        "query": query,
        "page": 1,
        "per_page": n_results,
    }

    return SearchResponse(projects=search_projects(**args), runs=search_runs(**args))
