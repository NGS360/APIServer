#!/usr/bin/env python
'''
This script reindexes the project table in OpenSearch
'''
import sys

from core.opensearch import get_opensearch_client
from core.logger import logger
from core.db import get_session

# Import all models first to ensure proper SQLAlchemy relationship resolution
from api.project.models import Project, ProjectAttribute
from api.samples.models import Sample, SampleAttribute
from api.runs.models import SequencingRun

from api.project.services import get_projects
from api.runs.services import get_runs

from api.search.models import SearchObject, SearchAttribute
from api.search.services import add_object_to_index

def reset_index(client, index):
    # Clear the existing index
    if client.indices.exists(index=index):
        client.indices.delete(index=index)

    # Create a new index
    client.indices.create(index=index, ignore=400)

def reindex_sequencingruns(client, session, index="illumina_runs"):
    reset_index(client, index)

    # Fetch all runs using pagination
    page = 1
    per_page = 1000  # Reasonable page size for reindexing
    total_indexed = 0

    while True:
        logger.info(f"Fetching runs page {page} (per_page={per_page})")
        
        # Call get_runs with proper parameters
        runs_response = get_runs(
            session=session,
            page=page,
            per_page=per_page,
            sort_by="id",
            sort_order="asc"
        )

        # If no run on this page, we're done
        if not runs_response.data:
            break

        # Index all runs from this page
        for run in runs_response.data:
            logger.debug(f"Reindexing run {run.barcode}")
            attributes = [
                SearchAttribute(key="machine_id", value=run.machine_id),
                SearchAttribute(key="flowcell_id", value=run.flowcell_id),
                SearchAttribute(key="experiment_name", value=run.experiment_name),
            ]

            search_object = SearchObject(
                id=run.barcode,
                name=run.experiment_name if run.experiment_name else run.barcode,
                attributes=attributes
            )

            add_object_to_index(client, search_object, index)
            total_indexed += 1
        # Check if we've reached the last page
        if not runs_response.has_next:
            break
            
        page += 1
    client.indices.refresh(index=index)
    logger.info(f"Reindexing completed. Total runs indexed: {total_indexed}")


def reindex_projects(client, session, index="projects"):
    reset_index(client, index)

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
    client = get_opensearch_client()
    if not client:
        logger.error("OpenSearch client is not available.")
        sys.exit(-1)

    session = next(get_session())
    if not session:
        logger.error("Database session could not be created.")
        sys.exit(-1)

    reindex_projects(client, session)
    reindex_sequencingruns(client, session)
