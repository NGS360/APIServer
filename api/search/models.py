from typing import List, Dict
from pydantic import BaseModel, computed_field
from datetime import datetime
from enum import Enum

class SearchAttribute(BaseModel):
    key: str | None
    value: str | None

class SearchObject(BaseModel):
    id: str
    name: str
    index_name: str  # NEW: Track which index this result came from
    attributes: List[SearchAttribute] | None = None

    @computed_field
    def display_name(self) -> str:
        return f"{self.id}: {self.name}"

class SearchErrorType(str, Enum):
    INDEX_NOT_FOUND = "index_not_found"
    CONNECTION_ERROR = "connection_error"
    TIMEOUT_ERROR = "timeout_error"
    QUERY_ERROR = "query_error"
    PERMISSION_ERROR = "permission_error"
    UNKNOWN_ERROR = "unknown_error"

class SearchError(BaseModel):
    """Error information for failed index searches"""
    index_name: str
    error_type: SearchErrorType
    error_message: str
    timestamp: datetime

class IndexSearchResult(BaseModel):
    """Results for a single index with error handling"""
    index_name: str
    items: List[SearchObject]
    total: int
    page: int
    per_page: int
    has_next: bool
    has_prev: bool
    success: bool = True
    error: SearchError | None = None
    
    @computed_field
    def total_pages(self) -> int:
        return (self.total + self.per_page - 1) // self.per_page if self.per_page > 0 else 0

class MultiSearchPublic(BaseModel):
    """Multi-index search response"""
    results: Dict[str, IndexSearchResult]  # Key = index name
    query: str
    page: int
    per_page: int
    total_across_indexes: int
    indexes_searched: List[str]
    partial_failure: bool = False
    
    @computed_field
    def summary(self) -> Dict[str, int]:
        """Quick summary of results per index"""
        return {
            index_name: result.total
            for index_name, result in self.results.items()
        }
    
    @computed_field
    def success_rate(self) -> float:
        """Calculate percentage of successful index searches"""
        if not self.results:
            return 0.0
        successful = sum(1 for result in self.results.values() if result.success)
        return (successful / len(self.results)) * 100

# Keep legacy model for backward compatibility during development
class SearchPublic(BaseModel):
    items: List[SearchObject] | None = None
    total: int
    page: int
    per_page: int
