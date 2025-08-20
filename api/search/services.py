import asyncio
import time
import traceback
from typing import Literal, List, Dict
from datetime import datetime
from opensearchpy import OpenSearch, RequestError
from core.logger import logger
from core.opensearch import INDEXES
from api.search.models import (
    SearchObject, SearchPublic, IndexSearchResult, MultiSearchPublic,
    SearchError, SearchErrorType
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


def _create_error_result(
    index: str,
    page: int,
    per_page: int,
    error_type: SearchErrorType,
    error_message: str
) -> IndexSearchResult:
    """Create an error result for a failed index search"""
    return IndexSearchResult(
        index_name=index,
        items=[],
        total=0,
        page=page,
        per_page=per_page,
        has_next=False,
        has_prev=False,
        success=False,
        error=SearchError(
            index_name=index,
            error_type=error_type,
            error_message=error_message,
            timestamp=datetime.now(datetime.UTC)
        )
    )

def search_single_index(
    client: OpenSearch,
    index: str,
    query: str,
    page: int,
    per_page: int,
    sort_by: str | None,
    sort_order: Literal['asc', 'desc'] | None
) -> IndexSearchResult:
    """
    Search a single index with comprehensive error handling
    """
    try:
        # Validate index exists
        if not client.indices.exists(index=index):
            return _create_error_result(
                index, page, per_page,
                SearchErrorType.INDEX_NOT_FOUND,
                f"Index '{index}' does not exist"
            )

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
                index_name=index,  # Add index name to each result
                attributes=hit["_source"].get("attributes", [])
            ) for hit in response["hits"]["hits"]
        ]

        total = response["hits"]["total"]["value"]
        
        return IndexSearchResult(
            index_name=index,
            items=items,
            total=total,
            page=page,
            per_page=per_page,
            has_next=(page * per_page) < total,
            has_prev=page > 1,
            success=True
        )

    except ConnectionError as e:
        logger.error(f"Connection error for index '{index}': {str(e)}")
        return _create_error_result(
            index, page, per_page,
            SearchErrorType.CONNECTION_ERROR,
            f"Failed to connect to OpenSearch: {str(e)}"
        )
        
    except RequestError as e:
        logger.error(f"Query error for index '{index}': {str(e)}")
        error_type = SearchErrorType.PERMISSION_ERROR if "security" in str(e).lower() else SearchErrorType.QUERY_ERROR
        return _create_error_result(
            index, page, per_page,
            error_type,
            f"Query failed: {str(e)}"
        )
        
    except Exception as e:
        logger.error(f"Unexpected error for index '{index}': {str(e)}\n{traceback.format_exc()}")
        return _create_error_result(
            index, page, per_page,
            SearchErrorType.UNKNOWN_ERROR,
            f"Unexpected error: {str(e)}"
        )

async def search_single_index_async(
    client: OpenSearch,
    index: str,
    query: str,
    page: int,
    per_page: int,
    sort_by: str | None,
    sort_order: Literal['asc', 'desc'] | None,
    timeout: float = 10.0
) -> IndexSearchResult:
    """
    Async wrapper for single index search with timeout
    """
    try:
        # Execute search with timeout
        loop = asyncio.get_event_loop()
        result = await asyncio.wait_for(
            loop.run_in_executor(
                None,
                search_single_index,
                client, index, query, page, per_page, sort_by, sort_order
            ),
            timeout=timeout
        )
        return result
        
    except asyncio.TimeoutError:
        logger.error(f"Search timeout for index '{index}' after {timeout}s")
        return _create_error_result(
            index, page, per_page,
            SearchErrorType.TIMEOUT_ERROR,
            f"Search timed out after {timeout} seconds"
        )

async def multi_search(
    client: OpenSearch,
    indexes: List[str],
    query: str,
    page: int,
    per_page: int,
    sort_by: str | None,
    sort_order: Literal['asc', 'desc'] | None
) -> MultiSearchPublic:
    """
    Search multiple indexes in parallel with individual pagination
    """
    if not client:
        logger.error("OpenSearch client is not available.")
        return MultiSearchPublic(
            results={},
            query=query,
            page=page,
            per_page=per_page,
            total_across_indexes=0,
            indexes_searched=[],
            partial_failure=True
        )
    
    # Validate indexes
    valid_indexes = [idx for idx in indexes if idx in INDEXES]
    if not valid_indexes:
        logger.warning(f"No valid indexes found in {indexes}. Valid indexes: {INDEXES}")
        return MultiSearchPublic(
            results={},
            query=query,
            page=page,
            per_page=per_page,
            total_across_indexes=0,
            indexes_searched=[],
            partial_failure=True
        )
    
    # Execute searches in parallel
    tasks = [
        search_single_index_async(client, index, query, page, per_page, sort_by, sort_order)
        for index in valid_indexes
    ]
    
    try:
        # Wait for all searches to complete (with timeout)
        results = await asyncio.wait_for(
            asyncio.gather(*tasks, return_exceptions=True),
            timeout=30.0  # 30 second timeout for all searches
        )
    except asyncio.TimeoutError:
        logger.error("Multi-search timed out after 30 seconds")
        results = [_create_error_result(
            idx, page, per_page,
            SearchErrorType.TIMEOUT_ERROR,
            "Multi-search timed out after 30 seconds"
        ) for idx in valid_indexes]
    
    # Process results
    search_results = {}
    total_across_indexes = 0
    has_errors = False
    
    for i, result in enumerate(results):
        index_name = valid_indexes[i]
        
        if isinstance(result, Exception):
            logger.error(f"Search failed for index '{index_name}': {str(result)}")
            # Create empty result for failed index
            search_results[index_name] = _create_error_result(
                index_name, page, per_page,
                SearchErrorType.UNKNOWN_ERROR,
                f"Unhandled exception: {str(result)}"
            )
            has_errors = True
        else:
            search_results[index_name] = result
            if result.success:
                total_across_indexes += result.total
            else:
                has_errors = True
    
    return MultiSearchPublic(
        results=search_results,
        query=query,
        page=page,
        per_page=per_page,
        total_across_indexes=total_across_indexes,
        indexes_searched=valid_indexes,
        partial_failure=has_errors
    )

# Legacy function for backward compatibility during development
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
    Legacy single-index search function
    """
    result = search_single_index(client, index, query, page, per_page, sort_by, sort_order)
    
    # Convert IndexSearchResult back to SearchPublic for compatibility
    return SearchPublic(
        items=result.items,
        total=result.total,
        page=result.page,
        per_page=result.per_page
    )
