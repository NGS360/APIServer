"""
User search models - request/response schemas
"""
from sqlmodel import SQLModel


class UserSearchResult(SQLModel):
    """Unified user search result from either LDAP or database"""
    username: str
    email: str | None = None
    full_name: str | None = None
    department: str | None = None
    title: str | None = None
    source: str  # "ldap" or "database"


class UserSearchResponse(SQLModel):
    """User search response"""
    data: list[UserSearchResult]
    count: int
    query: str
    source: str  # "ldap" or "database" - indicates which source was used
