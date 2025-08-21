from typing import List, Dict, Any, Union
from pydantic import BaseModel, computed_field
from api.project.models import ProjectPublic
from api.runs.models import SequencingRunPublic

#class SearchAttribute(BaseModel):
#  key: str | None
#  value: str | None

#class SearchObject(BaseModel):
#    id: str
#    name: str
#    attributes: List[SearchAttribute] | None = None

#    @computed_field
#    def display_name(self) -> str:
#        return f"{self.id}: {self.name}"

class SearchDocument(BaseModel):
    id: str
    body: Any

#class SearchPublic(BaseModel):
#    data: List[SearchObject] | None = None
#    total_items: int = 0
#    total_pages: int = 0
#    current_page: int = 1
#    per_page: int = 0
#    has_next: bool = False
#    has_prev: bool = False

class DynamicSearchResponse(BaseModel):
    """
    Dynamic search response that can have different field names based on the index.
    This allows for 'projects' key when searching projects index, 'runs' key when searching runs index, etc.
    The data field will contain the appropriate model type based on the index.
    """
    model_config = {"extra": "allow"}  # Allow extra fields to be set dynamically
    
    total_items: int = 0
    total_pages: int = 0
    current_page: int = 1
    per_page: int = 0
    has_next: bool = False
    has_prev: bool = False
    
    # Dynamic fields that will be set based on index:
    # - projects: List[ProjectPublic]
    # - illumina_runs: List[SequencingRunPublic]
    # - data: List[SearchObject] (fallback)
