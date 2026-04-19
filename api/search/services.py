"""
Search-related services
"""
from opensearchpy import OpenSearch, helpers
from sqlmodel import Session

from core.logger import logger

from api.search.models import (
    SearchDocument,
    SearchResponse,
)


def add_objects_to_index(
    client: OpenSearch, documents: list[SearchDocument], index: str
) -> None:
    """
    Add multiple documents to the OpenSearch index in one bulk operation.

    Args:
        client: OpenSearch client
        documents: List of SearchDocument objects to index
        index: The index name
    """
    if client is None:
        logger.warning("OpenSearch client is not available.")
        return

    if not documents:
        logger.info("No documents to index.")
        return

    # Prepare bulk actions
    actions = []
    for document in documents:
        payload = {}
        for field in document.body.__searchable__:
            value = getattr(document.body, field)
            if value:
                payload[field] = value

        action = {
            "_index": index,
            "_id": str(document.id),
            "_source": payload
        }
        actions.append(action)

    # Perform bulk indexing
    try:
        success, failed = helpers.bulk(
            client, actions, raise_on_error=False, stats_only=False)
        logger.info(f"Bulk indexed {success} documents successfully")
        if failed:
            logger.warning(f"Failed to index {len(failed)} documents")

        # Refresh the index once after bulk operation
        client.indices.refresh(index=index)
    except Exception as e:
        logger.error(f"Bulk indexing failed: {e}")
        raise


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


def delete_document_from_index(
    client: OpenSearch, document_id: str, index: str
) -> None:
    """
    Delete a single document from an OpenSearch index.

    Args:
        client: OpenSearch client
        document_id: The document ID to delete
        index: The index name
    """
    if client is None:
        logger.warning("OpenSearch client is not available.")
        return

    try:
        client.delete(index=index, id=document_id, ignore=[404])
        client.indices.refresh(index=index)
    except Exception as e:
        logger.warning("Failed to delete document %s from index %s: %s", document_id, index, e)


def reset_index(client: OpenSearch, index: str) -> None:
    # Clear the existing index
    if client.indices.exists(index=index):
        client.indices.delete(index=index)

    # Create a new index
    client.indices.create(index=index, ignore=400)


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
