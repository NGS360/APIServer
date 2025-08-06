from core.logger import logger
from core.opensearch import get_session
from api.project.models import (
   Project
)

def add_project_to_index(project: Project) -> None:
    """
    Add the project to the OpenSearch index.
    """
    # Assuming you have an OpenSearch client set up
    with get_session() as session:
        if session is None:
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
        session.index(index="projects", id=str(project.id), body=doc)
        session.indices.refresh(index="projects")
