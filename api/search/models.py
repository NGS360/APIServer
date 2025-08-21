from typing import List, Dict, Any
from pydantic import BaseModel, computed_field

class SearchAttribute(BaseModel):
  key: str | None
  value: str | None

class SearchObject(BaseModel):
    id: str
    name: str
    attributes: List[SearchAttribute] | None = None

    @computed_field
    def display_name(self) -> str:
        return f"{self.id}: {self.name}"

class SearchPublic(BaseModel):
    data: List[SearchObject] | None = None
    total_items: int = 0
    total_pages: int = 0
    current_page: int = 1
    per_page: int = 0
    has_next: bool = False
    has_prev: bool = False

class DynamicSearchResponse(BaseModel):
    """
    Dynamic search response that can have different field names based on the index.
    This allows for 'projects' key when searching projects index, 'runs' key when searching runs index, etc.
    """
    model_config = {"extra": "allow"}  # Allow extra fields to be set dynamically
    
    total_items: int = 0
    total_pages: int = 0
    current_page: int = 1
    per_page: int = 0
    has_next: bool = False
    has_prev: bool = False
