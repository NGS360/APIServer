"""
Models for the Chat API
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict


class ChatRequest(BaseModel):
    """Incoming chat message from the frontend."""

    model_config = ConfigDict(extra="forbid")

    message: str
    conversation_id: str | None = None
    stream: bool = True


class ChatResponse(BaseModel):
    """Non-streaming response containing the full agent reply."""

    response: str
    conversation_id: str


class ChatStreamEvent(BaseModel):
    """A single SSE event in the streaming response."""

    event: Literal["text", "error", "done"]
    data: str
    conversation_id: str | None = None
