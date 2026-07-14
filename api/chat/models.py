"""
Models for the AI Assistant Chat API
"""

from pydantic import BaseModel, Field


class ChatContextEntity(BaseModel):
    """An entity attached to a chat message: type ("project", "run", "sample",
    "user", ...) and its id."""

    type: str
    id: str


class ChatContext(BaseModel):
    """Context the user attached when sending a message: the page they're on
    and any entities they referenced via "@/#", so the assistant can scope its
    answer."""

    page: ChatContextEntity | None = None
    references: list[ChatContextEntity] = []


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=10000)
    thread_id: str | None = None
    context: ChatContext | None = None
