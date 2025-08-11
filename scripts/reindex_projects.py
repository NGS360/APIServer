#!/usr/bin/env python
'''
This script reindexes the project table in OpenSearch
'''
from core.opensearch import client
from core.logger import logger
from core.db import get_session

from api.project.services import get_projects
from api.search.models import SearchObject, SearchAttribute
from api.search.services import add_object_to_index

def reindex(index='projects'):
    if not client:
        logger.error("OpenSearch client is not available.")
        return

    session = next(get_session())
    if not session:
        logger.error("Database session could not be created.")
        return

    # Clear the existing index
    if client.indices.exists(index=index):
        client.indices.delete(index=index)

    # Create a new index
    client.indices.create(index=index, ignore=400)

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

if __name__ == "__main__":
    reindex()
