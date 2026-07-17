"""
Models for the AI Assistant Chat API
"""

from pydantic import BaseModel, ConfigDict, Field


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


class UIMessagePart(BaseModel):
    """One part of a Vercel AI SDK UIMessage. Text parts carry ``text``; other
    part types (tool calls, files, ...) are tolerated and ignored."""

    model_config = ConfigDict(extra="ignore")

    type: str
    text: str | None = None


class UIMessage(BaseModel):
    """A Vercel AI SDK UIMessage: a role plus an ordered list of typed parts."""

    model_config = ConfigDict(extra="ignore")

    id: str | None = None
    role: str  # "user" | "assistant" | "system"
    parts: list[UIMessagePart] = []


class ChatRequest(BaseModel):
    """The default request body sent by the frontend's useChat hook (Vercel AI
    SDK). The stable chat ``id`` doubles as the LangGraph thread id, so
    multi-turn continuity needs no extra round-trip. ``context`` is merged in by
    the SDK from ``sendMessage(text, {body: {context}})``."""

    model_config = ConfigDict(extra="ignore")

    id: str
    messages: list[UIMessage] = Field(min_length=1)
    trigger: str | None = None  # "submit-message" | "regenerate-message"
    context: ChatContext | None = None
