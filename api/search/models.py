from typing import List, Dict, Any, Union
from pydantic import BaseModel, computed_field
from api.project.models import ProjectPublic
from api.runs.models import SequencingRunPublic

class SearchDocument(BaseModel):
    id: str
    body: Any # This object has to have a __searchable__ property

class SearchResponse(BaseModel):
    total_items: int = 0
    total_pages: int = 0
    current_page: int = 1
    per_page: int = 0
    has_next: bool = False
    has_prev: bool = False

    model_config = {"extra": "allow"}  # Allow extra fields to be set dynamically
    # Dynamic fields that will be set based on index:
    # - projects: List[ProjectPublic]
    # - illumina_runs: List[SequencingRunPublic]
    # - data: List[SearchObject] (fallback)
