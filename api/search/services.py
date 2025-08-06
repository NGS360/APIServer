from core.logger import logger
from core.opensearch import client
from api.project.models import (
   Project
)

def add_project_to_index(project: Project) -> None:
    """
    Add the project to the OpenSearch index.
    """
    # Assuming you have an OpenSearch client set up
    if client is None:
        logger.warning("OpenSearch client is not available.")
        return

    # Prepare the document to index
    doc = {
        "project_id": str(project.project_id),
        "name": project.name,
        "attributes": [
            {"key": attr.key, "value": attr.value} for attr in project.attributes or []
        ]
    }

    # Index the document
    client.index(index="projects", id=str(project.id), body=doc)
    client.indices.refresh(index="projects")
