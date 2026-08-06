"""
Models for the AI Assistant Chat API

Two halves, marked by the section banners below:

* REQUEST AND THREAD MODELS — the JSON bodies of the chat routes.
* THE CHAT STREAM'S WIRE CONTRACT — one model per SSE frame of POST
  /chat/stream. These are not a JSON body: they are the frames of a
  text/event-stream, one per ``data:`` line.
"""

import uuid
from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, RootModel

# ---------------------------------------------------------------------------
# Request and thread models
# ---------------------------------------------------------------------------


# Define accepted chat entity types
ChatEntityType = Literal["project", "run", "sample", "job", "user"]

# Limits the number of context references that can be pushed
MAX_CONTEXT_REFERENCES = 20


class ChatContextEntity(BaseModel):
    """An entity attached to a chat message: its kind and its id.

    Ids are business keys (``project.project_id``, ``users.username``, ...), not
    the uuid primary keys, which the public API does not expose.

    ``project_id`` scopes a sample, whose id is unique only within a project (i.e. sample).
    Ignored for every other kind.
    """

    type: ChatEntityType
    id: str
    project_id: str | None = None


class ChatContext(BaseModel):
    """Context the user attached when sending a message: the page they're on
    and any entities they referenced via "@/#", so the assistant can scope its
    answer.

    All user-controlled: it comes from the request body. Who is asking is not
    part of it — ``services.build_run_context`` adds that from the session.
    """

    page: ChatContextEntity | None = None
    references: list[ChatContextEntity] = Field(
        default=[], max_length=MAX_CONTEXT_REFERENCES
    )


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


# ---------------------------------------------------------------------------
# The chat stream's wire contract: one model per SSE frame
# ---------------------------------------------------------------------------
#
# Our own shape, not the AI SDK's. The browser speaks that protocol, but the
# translation belongs to the client, where the SDK is installed and the compiler
# can check it (frontend-ui/src/lib/chat-transport.ts).
#
# Models rather than dict literals because they become the OpenAPI schema the
# client generates its types from and binds its validator to — so renaming a
# field here fails the frontend build instead of silently emitting frames the
# browser discards.


class ChatFrameThread(BaseModel):
    """The thread this turn belongs to. Sent first, so a new thread's id
    survives a run that then fails."""

    type: Literal["thread"] = "thread"
    thread_id: str


class ChatFrameStatus(BaseModel):
    """The running tool's name, never its args or output. Opaque — the client
    derives a label, so an unknown tool still renders."""

    type: Literal["status"] = "status"
    tool: str


class ChatFrameText(BaseModel):
    """One token of the answer."""

    type: Literal["text"] = "text"
    delta: str


class ChatFrameDone(BaseModel):
    """The run finished cleanly, as opposed to the connection dropping."""

    type: Literal["done"] = "done"


class ChatFrameError(BaseModel):
    """The run failed. Replaces ``done`` rather than preceding it."""

    type: Literal["error"] = "error"
    message: str


# Discriminated, so a bad ``type`` is an error rather than a silent match.
ChatFrame = Annotated[
    ChatFrameThread
    | ChatFrameStatus
    | ChatFrameText
    | ChatFrameDone
    | ChatFrameError,
    Field(discriminator="type"),
]


class ChatFrameEnvelope(RootModel[ChatFrame]):
    """The union as a referenceable schema, for OpenAPI only. No route returns
    it; it exists so the stream route can put the frames in /docs."""
