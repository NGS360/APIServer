from typing import List, Dict, Any, Union
from pydantic import BaseModel, computed_field
from api.project.models import ProjectPublic, ProjectsPublic
from api.runs.models import SequencingRunPublic, SequencingRunsPublic


class SearchDocument(BaseModel):
    id: str
    body: Any  # This object has to have a __searchable__ property


class BaseSearchResponse(BaseModel):
    """Base response model with common pagination fields"""

    total_items: int = 0
    total_pages: int = 0
    current_page: int = 1
    per_page: int = 0
    has_next: bool = False
    has_prev: bool = False


class ProjectSearchResponse(BaseSearchResponse):
    """Response model for project searches"""

    projects: List[ProjectPublic] = []


class RunSearchResponse(BaseSearchResponse):
    """Response model for sequencing run searches"""

    illumina_runs: List[SequencingRunPublic] = []


class GenericSearchResponse(BaseSearchResponse):
    """Fallback response model for other search types"""

    data: List[SearchDocument] = []


# Union type for all possible search responses
SearchResponseOriginal = Union[
    ProjectSearchResponse, RunSearchResponse, GenericSearchResponse
]


class SearchResponse(BaseModel):
    projects: ProjectsPublic
    runs: SequencingRunsPublic
