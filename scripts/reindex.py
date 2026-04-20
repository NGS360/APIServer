#!/usr/bin/env python
'''
This script reindexes the project and runs table in OpenSearch

Usage: PYTHONPATH=. python3 -m pudb scripts/reindex.py [--index-projects] [--index-runs]

'''
import sys
from sqlmodel import select

from core.opensearch import get_opensearch_client
from core.logger import logger
from core.db import get_session

# Import all models first to ensure proper SQLAlchemy relationship resolution
from api.project.models import Project
from api.runs.models import SequencingRun
from api.samples.models import Sample  # noqa: F401
from api.search.models import SearchDocument
from api.runs.services import search_runs
from api.search.services import add_objects_to_index
from api.qcmetrics.models import QCMetric, QCRecord  # noqa: F401


def reset_index(client, index):
    # Clear the existing index
    if client.indices.exists(index=index):
        client.indices.delete(index=index)

    # Create a new index
    client.indices.create(index=index, ignore=400)


def reindex_sequencingruns(client, session, index="illumina_runs"):
    runs = session.exec(
        select(SequencingRun)
    ).all()

    # Sort the runs by barcode to ensure consistent indexing order
    runs.sort(key=lambda r: r.barcode)

    # Prepare all documents
    search_docs = []
    for run in runs:
        logger.debug(f"Preparing run {run.barcode} for indexing")
        search_doc = SearchDocument(id=run.barcode, body=run)
        search_docs.append(search_doc)

    reset_index(client, index)
    # Bulk index all documents in one call
    add_objects_to_index(client, search_docs, index)

    logger.info(f"Reindexing completed. Total runs indexed: {len(runs)}")


def reindex_projects(client, session, index="projects"):
    projects = session.exec(
        select(Project).order_by(Project.project_id)
    ).all()

    # Prepare all documents
    search_docs = []
    for project in projects:
        logger.debug(f"Preparing project {project.project_id} for indexing")
        search_doc = SearchDocument(id=project.project_id, body=project)
        search_docs.append(search_doc)

    reset_index(client, index)
    # Bulk index all documents in one call
    add_objects_to_index(client, search_docs, index)

    logger.info(f"Reindexing completed. Total projects indexed: {len(projects)}")


def test_illumina_runs(client, session):
    runs = search_runs(
        session,
        client,
        query="",
        page=1,
        per_page=10,
        sort_by="barcode",
        sort_order="desc"
    )
    logger.info(f"Test search returned {len(runs.data)} runs")


def parse_args():
    import argparse

    parser = argparse.ArgumentParser(
        description="Reindex projects and sequencing runs in OpenSearch")

    parser.add_argument(
        "--index-projects",
        action="store_true",
        default=False,
        help="Reindex projects")
    parser.add_argument(
        "--index-runs",
        action="store_true",
        default=False,
        help="Reindex sequencing runs")

    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    client = get_opensearch_client()
    if not client:
        logger.error("OpenSearch client is not available.")
        sys.exit(-1)

    session = next(get_session())
    if not session:
        logger.error("Database session could not be created.")
        sys.exit(-1)

    if args.index_projects:
        logger.info("Reindexing projects...")
        reindex_projects(client, session)
    if args.index_runs:
        logger.info("Reindexing sequencing runs...")
        reindex_sequencingruns(client, session)

    logger.info("Testing Illumina runs index...")
    test_illumina_runs(client, session)
