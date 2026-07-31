"""
Models for the AI Assistant Chat API
"""

import uuid
from datetime import datetime

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
    """The request body sent by the frontend's useChat hook (Vercel AI SDK).

    ``id`` is the SDK's own conversation id — opaque to us, and deliberately not
    the thread id. ``thread_id`` and ``context`` are merged in by the SDK from
    ``sendMessage(text, {body: {...}})``: absent ``thread_id`` starts a new
    thread, which the server creates and announces in the stream.
    """

    model_config = ConfigDict(extra="ignore")

    id: str
    messages: list[UIMessage] = Field(min_length=1)
    trigger: str | None = None  # "submit-message" | "regenerate-message"
    thread_id: uuid.UUID | None = None
    context: ChatContext | None = None


class ChatThreadPublic(BaseModel):
    """One of the caller's chat threads.

    Threads aren't stored here — they belong to the agent deployment, and are
    listed by the owner recorded in each thread's metadata. ``id`` is the thread
    id, which is also the chat id the UI sends. ``title`` is derived from the
    thread's first message; the agent stores no title of its own.
    """

    id: str
    title: str
    created_at: datetime | None = None
    updated_at: datetime | None = None


class ChatThreadsPublic(BaseModel):
    """A page of chat threads, shaped like the other list endpoints."""

    data: list[ChatThreadPublic]
    total_items: int
    total_pages: int
    current_page: int
    per_page: int
    has_next: bool
    has_prev: bool


class ChatThreadMessages(BaseModel):
    """A thread's messages as the user saw them, ready to replay in the chat UI.

    The agent's tool calls and raw query output are filtered out, and what's left
    is mapped to AI SDK UIMessages. Fetch the thread itself for the full
    checkpointed state, tool output included.
    """

    thread_id: str
    messages: list[UIMessage] = []
