#!/usr/bin/env python
'''
This script reindexes the project table in OpenSearch
'''
import sys
from sqlmodel import select

from core.opensearch import get_opensearch_client
from core.logger import logger
from core.db import get_session

# Import all models first to ensure proper SQLAlchemy relationship resolution
from api.project.models import Project, ProjectAttribute
from api.samples.models import Sample, SampleAttribute
from api.runs.models import SequencingRun

from api.search.models import SearchDocument
from api.search.services import add_object_to_index

def reset_index(client, index):
    # Clear the existing index
    if client.indices.exists(index=index):
        client.indices.delete(index=index)

    # Create a new index
    client.indices.create(index=index, ignore=400)

def reindex_sequencingruns(client, session, index="illumina_runs"):
    reset_index(client, index)

    runs = session.exec(
        select(SequencingRun)
    ).all()

    # Index all runs from this page
    for run in runs:
        logger.debug(f"Reindexing run {run.barcode}")

        search_doc = SearchDocument(id=run.barcode, body=run)
        add_object_to_index(client, search_doc, index)

    logger.info(f"Reindexing completed. Total runs indexed: {len(runs)}")


def reindex_projects(client, session, index="projects"):
    reset_index(client, index)

    projects = session.exec(
        select(Project)
    ).all()

    # Index all projects from this page
    for project in projects:
        logger.debug(f"Reindexing project {project.project_id}")

        search_doc = SearchDocument(id=project.project_id, body=project)
        add_object_to_index(client, search_doc, index)

    logger.info(f"Reindexing completed. Total projects indexed: {len(projects)}")

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
