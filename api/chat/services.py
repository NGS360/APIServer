"""
Chat-related services

Invokes the deployed NGS360 SQL Agent (LangGraph Platform) and adapts its token
stream into this API's own SSE frames, which the frontend's chat transport maps
onto the Vercel AI SDK UI Message Stream protocol for useChat.

The stream carries the answer's text, the thread id, and the name of whichever
tool is running — nothing else about how the agent got there. No text arrives
while the agent works, which is what the client renders as "Thinking…", so that
absence is load-bearing.

Sections below, in dependency order:

1. Reading the agent graph's messages — everything coupled to a graph we don't
   own.
2. Thread lifecycle — ownership, listing, transcripts, deletion.
3. Invoking the agent — the non-streaming reply.
4. Streaming the answer — SSE framing and ordering.
"""

import asyncio
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, AsyncGenerator

from fastapi import HTTPException
from langgraph_sdk.errors import NotFoundError

from api.auth.models import User
from api.chat.models import (
    ChatContext,
    ChatFrame,
    ChatFrameDone,
    ChatFrameError,
    ChatFrameStatus,
    ChatFrameText,
    ChatFrameThread,
    ChatRequest,
)
from core.config import get_settings
from core.security import create_access_token

# Wall-clock ceilings for a single upstream invocation.
NON_STREAMING_TIMEOUT_S = 60
STREAMING_TIMEOUT_S = 120

# Run-config key carrying a credential for the calling user to the agent, so its
# NGS360 API tools act as that user and that API's per-user permissions apply. The
# agent reads exactly this name (NGS360-Agent: agents/ngs360_agent/mcp_user_auth.py);
# both sides must change together.
#
# The `__` prefix and the word "token" are both load-bearing, at different layers.
# LangGraph copies scalar `configurable` values into persisted checkpoint metadata,
# skipping only keys starting with `__`
# (langgraph.checkpoint.base.get_checkpoint_metadata). For LangSmith traces there
# are two filters, because langgraph defines its own get_callback_manager_for_config
# shadowing langchain-core's and each reaches a different one: the top-level run
# (langgraph.pregel.main) goes through langchain-core's, which excludes an
# exact-match `api_key` only, while per-node runs (langgraph._internal._runnable)
# go through langgraph's, which drops any key containing
# key/token/secret/password/auth (langgraph._internal._config._exclude_as_metadata).
# So `__` is what holds everywhere, and "token" adds cover at the node layer.
# Renaming this can start persisting credentials.
USER_TOKEN_CONFIG_KEY = "__ngs360_user_token"

# How long the agent's delegated credential stays valid. Long enough to outlive a
# run (see STREAMING_TIMEOUT_S above), short enough that what leaves this process
# is not a session-lifetime credential.
DELEGATED_TOKEN_TTL = timedelta(minutes=5)

# Marks a token as minted for the chat agent rather than issued to a browser. Inert
# today — get_current_user reads only `sub` — and the hook for a future
# "the agent may not do X" once there is an authorization layer to ask.
AGENT_ACTOR = "chat-agent"


def mint_delegated_token(user: User) -> str:
    """A short-lived credential the agent uses to act as this user.

    Minted rather than replayed. The caller's own bearer credential would also
    work — the agent's tools call back into this same API — but replaying it sends
    either a session token or an `ngs360_` API key, and an API key may have no
    expiry at all (APIKey.expires_at defaults to None). Minting makes what leaves
    the process short-lived and single-purpose by construction rather than by
    argument, and it is never the credential the user logs in with.

    It authenticates through the unchanged path: decode_token verifies signature
    and expiry, and get_current_user resolves `sub`, so this arrives as the same
    user who asked.

    Note what this enables by design: the agent may write as this user, so
    untrusted text it reads — project descriptions, sample metadata, file
    contents — is a path to writes under the caller's own permissions. What bounds
    it is the agent's own gate (destructive tools are never loaded) and this
    token's lifetime, not anything on this side of the call.
    """
    return create_access_token(
        {"sub": str(user.id), "act": AGENT_ACTOR},
        expires_delta=DELEGATED_TOKEN_TTL,
    )


def user_run_config(user_token: str | None) -> dict[str, Any] | None:
    """The run config that makes the agent act as this user.

    None when there is no credential to forward, so the agent falls back to its
    read-only posture rather than being handed an empty string to treat as one.

    The token reaches LangGraph Platform and is stored on the run row, which is
    inside that platform's at-rest encryption set. DELEGATED_TOKEN_TTL is what
    bounds how long that stored copy is worth anything.
    """
    if not user_token:
        return None
    return {"configurable": {USER_TOKEN_CONFIG_KEY: user_token}}


# ---------------------------------------------------------------------------
# 1. Reading the agent graph's messages
# ---------------------------------------------------------------------------
#
# The graph is in another repository, so its node names and message shapes are
# assumptions. Everything here skips what it doesn't recognize rather than
# raising, and the chunks are deliberately not modelled — a strict model would
# turn "the graph added a field" into a 502 on every message.

# The only node that produces the user-facing answer. Text is gated to it so a
# node we don't expect to speak cannot narrate over the reply.
FINAL_ANSWER_NODE = "reasoning"

# The token/metadata pairs that make up the answer. Nothing else is read.
STREAM_MODE = "messages-tuple"


def message_role(msg: dict[str, Any]) -> str:
    """Normalize a message's role. LangGraph uses ``type``; tests use ``role``."""
    return str(msg.get("role", msg.get("type", ""))).lower()


def extract_text_from_message(msg: dict[str, Any]) -> str:
    """Flatten a LangChain-style message ``content`` (str or list of parts) to text."""
    content = msg.get("content", "")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, dict) and "text" in item:
                parts.append(str(item["text"]))
            else:
                parts.append(str(item))
        return "".join(parts)
    return str(content)


def chunk_text(msg: dict[str, Any]) -> str:
    """The text of a message chunk, ignoring blocks that aren't text.

    Unlike extract_text_from_message, never stringifies a block it doesn't
    understand: content lists also carry tool_use blocks.
    """
    content = msg.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict) and isinstance(item.get("text"), str):
                if item.get("type", "text") in {"text", "text_delta"}:
                    parts.append(item["text"])
        return "".join(parts)
    return ""


def is_tool_message(msg: dict[str, Any]) -> bool:
    """Is this a tool result rather than the model's own output?

    Only used to exclude it: the node filter alone would not stop a result
    routed through FINAL_ANSWER_NODE. Role is matched by prefix because ``type``
    is "tool" or "ToolMessageChunk" depending on how the graph sends it.
    """
    if message_role(msg).startswith("tool"):
        return True
    return bool(msg.get("tool_call_id"))


def tool_names_requested(msg: dict[str, Any]) -> list[str]:
    """The names of the tools an assistant message asks for, in order.

    Both shapes: a whole ``AIMessage`` carries ``tool_calls``, a streamed chunk
    carries ``tool_call_chunks``. Only the name is read — the ``args`` beside it
    must not leave the server. Unusable names are skipped, leaving the previous
    label up rather than blanking it.
    """
    names: list[str] = []
    for key in ("tool_calls", "tool_call_chunks"):
        calls = msg.get(key)
        if not isinstance(calls, list):
            continue
        for call in calls:
            if not isinstance(call, dict):
                continue
            name = call.get("name")
            if isinstance(name, str) and name.strip():
                names.append(name.strip())
    return names


def message_tuple(data: Any) -> tuple[dict[str, Any], dict[str, Any]] | None:
    """A ``messages-tuple`` payload as (message, metadata), or None if it isn't one.

    The pair arrives as a list once it has been through JSON, so the shape is
    checked rather than unpacked blindly.
    """
    if isinstance(data, (list, tuple)) and len(data) == 2:
        message, metadata = data
        if isinstance(message, dict):
            return message, metadata if isinstance(metadata, dict) else {}
    return None


def upstream_error_text(data: Any) -> str:
    """The message from an ``error`` stream event, as an error frame's text.

    The payload's shape is the graph's, so both keys it might use are tried and
    an unusable one still yields something to show.
    """
    if isinstance(data, dict):
        for key in ("message", "error"):
            value = data.get(key)
            if isinstance(value, str) and value.strip():
                detail = value.strip().replace("\n", " ")[:300]
                return f"Upstream error: {detail}"
    return "Upstream error"


def stream_event_kind(event: Any) -> str:
    """Which stream mode a LangGraph stream part came from.

    The event name is not always the bare mode: a subgraph namespaces it
    (``"node:1|messages"``) and the messages modes are sometimes suffixed
    (``"messages/partial"``). Anything unrecognized is returned as itself so the
    caller can ignore it.
    """
    if not isinstance(event, str):
        return ""
    name = event.split("|")[-1].split("/")[0].strip().lower()
    return "messages" if name.startswith("messages") else name


# ---------------------------------------------------------------------------
# 2. Thread lifecycle: ownership, listing, transcripts
# ---------------------------------------------------------------------------

# Records which user owns a thread. Ids are assigned here, but continuing a
# conversation means naming one, so this is what stops an authenticated user
# reaching someone else's — see require_owned_thread.
OWNER_METADATA_KEY = "ngs360_user_id"

# Optional per-thread title override, for when renaming is added. Until then a
# title is derived from the thread's first message.
TITLE_METADATA_KEY = "ngs360_title"
TITLE_MAX_LENGTH = 48

# Pulls each thread's first message out of its checkpointed state server-side,
# so listing costs one round trip and never ships whole transcripts.
FIRST_MESSAGE_EXTRACT = {"first_msg": "values.messages[0].content"}

# Deliberately excludes "values": with it, a list response would carry every
# transcript on the page.
LIST_SELECT = ["thread_id", "created_at", "updated_at", "metadata"]


async def require_owned_thread(
    client, thread_id: str, user_id: str
) -> dict[str, Any]:
    """The caller's thread, or 404 if it is absent or someone else's.

    Absent and not-yours both raise 404, not 403, so probing can't tell them
    apart. This is the only ownership gate: every route takes the thread id from
    the caller, so without it one user could read another's conversation.

    Only a genuine upstream 404 counts as "doesn't exist" — swallowing every
    error would fail open, letting a transient blip look like an absent thread.
    """
    try:
        thread = await client.threads.get(thread_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail="Thread not found") from exc
    except Exception as exc:
        raise HTTPException(
            status_code=502, detail="Could not verify thread ownership"
        ) from exc

    metadata = (thread or {}).get("metadata") or {}
    if metadata.get(OWNER_METADATA_KEY) != user_id:
        raise HTTPException(status_code=404, detail="Thread not found")
    return thread


async def resolve_thread(req: ChatRequest, client, user_id: str) -> str:
    """The thread this turn belongs to, creating one if the client has none.

    Ids are assigned here rather than accepted from the client. Naming a thread
    means continuing it, so it must pass the ownership check; naming one that is
    gone is a 404, and the client starts a new chat rather than resurrect the id.
    """
    if req.thread_id is not None:
        thread_id = str(req.thread_id)
        await require_owned_thread(client, thread_id, user_id)
        return thread_id

    thread_id = str(uuid.uuid4())
    try:
        await client.threads.create(
            thread_id=thread_id,
            metadata={
                OWNER_METADATA_KEY: user_id,
                "ngs360_created_at": datetime.now(timezone.utc).isoformat(),
            },
        )
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Thread creation failed: {type(exc).__name__}",
        ) from exc
    return thread_id


def derive_title(first_message: Any, metadata: dict[str, Any] | None) -> str:
    """Title for a thread: an explicit override, else its first message.

    Mirrors the truncation the UI used when it derived titles locally.
    """
    override = (metadata or {}).get(TITLE_METADATA_KEY)
    if isinstance(override, str) and override.strip():
        return override.strip()

    text = first_message if isinstance(first_message, str) else ""
    text = " ".join(text.split())
    if not text:
        return "New chat"
    if len(text) <= TITLE_MAX_LENGTH:
        return text
    return f"{text[:TITLE_MAX_LENGTH].rstrip()}…"


async def list_threads(
    client, user_id: str, skip: int, limit: int
) -> dict[str, Any]:
    """Page through the caller's chat threads, newest activity first.

    Filtered by the owner in thread metadata. There is no local table, so that
    metadata is the only place the user/thread association lives.
    """
    owner = {OWNER_METADATA_KEY: user_id}
    try:
        threads = await client.threads.search(
            metadata=owner,
            limit=limit,
            offset=skip,
            sort_by="updated_at",
            sort_order="desc",
            select=LIST_SELECT,
            extract=FIRST_MESSAGE_EXTRACT,
        )
        total_items = await client.threads.count(metadata=owner)
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Thread listing failed: {type(exc).__name__}",
        ) from exc

    data = []
    for thread in threads:
        metadata = thread.get("metadata") or {}
        extracted = thread.get("extracted") or {}
        data.append(
            {
                "id": thread.get("thread_id"),
                # A thread whose first turn failed has nothing to extract; it is
                # still listed (as "New chat") so the page count stays truthful.
                "title": derive_title(extracted.get("first_msg"), metadata),
                "created_at": thread.get("created_at"),
                "updated_at": thread.get("updated_at"),
            }
        )

    return {
        "data": data,
        "total_items": total_items,
        "total_pages": (total_items + limit - 1) // limit if limit else 0,
        "current_page": (skip // limit) + 1 if limit else 1,
        "per_page": limit,
        "has_next": skip + limit < total_items,
        "has_prev": skip > 0,
    }


def transcript_from_state(state: dict[str, Any]) -> list[dict[str, Any]]:
    """Rebuild the visible conversation from a thread's checkpointed state.

    Stored state holds the agent's whole working history, but the UI only ever
    saw the final answers, so two kinds of message are dropped: ``tool``
    messages (raw query output) and empty-content ``ai`` messages (the tool-call
    steps). What is left came from FINAL_ANSWER_NODE, the same node the live
    stream forwards — worth revisiting if the graph grows another talkative one.
    """
    messages: list[dict[str, Any]] = []
    for msg in state.get("messages") or []:
        if not isinstance(msg, dict):
            continue
        role = message_role(msg)
        text = extract_text_from_message(msg)
        if role in {"human", "user"}:
            out_role = "user"
        elif role in {"ai", "assistant"} and text.strip():
            out_role = "assistant"
        else:
            continue
        messages.append(
            {
                "id": msg.get("id") or f"msg_{uuid.uuid4().hex}",
                "role": out_role,
                "parts": [{"type": "text", "text": text}],
            }
        )
    return messages


async def get_thread_messages(client, thread_id: str) -> dict[str, Any]:
    """A thread as the user saw it: its transcript as UIMessages.

    Ownership is the route's OwnedThreadDep to enforce, so reach this only
    through a route that declares it.
    """
    try:
        state = await client.threads.get_state(thread_id)
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Thread lookup failed: {type(exc).__name__}",
        ) from exc

    return {
        "thread_id": thread_id,
        "messages": transcript_from_state(state.get("values") or {}),
    }


async def delete_thread(client, thread_id: str) -> None:
    """Delete one chat thread, agent memory included.

    Ownership is the route's OwnedThreadDep to enforce, so reach this only
    through a route that declares it.
    """
    try:
        await client.threads.delete(thread_id)
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Thread delete failed: {type(exc).__name__}",
        ) from exc


async def delete_all_threads(client, user_id: str) -> int:
    """Delete every chat thread belonging to the caller. Returns the count.

    Pages rather than trusting one search page, so "clear all" doesn't quietly
    leave older threads behind.
    """
    owner = {OWNER_METADATA_KEY: user_id}
    deleted = 0
    try:
        while True:
            threads = await client.threads.search(
                metadata=owner, limit=100, offset=0, select=["thread_id"]
            )
            if not threads:
                return deleted
            for thread in threads:
                await client.threads.delete(thread["thread_id"])
                deleted += 1
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Thread delete failed: {type(exc).__name__}",
        ) from exc


# ---------------------------------------------------------------------------
# 3. Invoking the agent: the non-streaming reply
# ---------------------------------------------------------------------------


def latest_user_text(req: ChatRequest) -> str:
    """Concatenate the text parts of the most recent user message.

    Scanning ``messages`` in reverse handles both the ``submit-message`` and
    ``regenerate-message`` triggers, since the last user turn is always present.
    """
    for msg in reversed(req.messages):
        if msg.role == "user":
            return "".join(p.text for p in msg.parts if p.type == "text" and p.text)
    return ""


def build_run_context(context: ChatContext | None, user: User) -> dict[str, Any]:
    """Assemble the runtime context handed to the agent for one run.

    The split between origins is the point: ``page`` and ``references`` are
    whatever the browser sent, while ``caller`` comes from the authenticated
    session and is never read from the body — a body-supplied identity would let
    a crafted request claim to be anyone.
    """
    payload: dict[str, Any] = {
        "caller": {"user_id": str(user.id), "username": user.username},
    }
    if context is None:
        return payload

    if context.page is not None:
        payload["page"] = context.page.model_dump(exclude_none=True)
    if context.references:
        payload["references"] = [
            reference.model_dump(exclude_none=True) for reference in context.references
        ]
    return payload


async def run_chat(
    req: ChatRequest,
    client,
    user_id: str,
    run_context: dict[str, Any] | None = None,
    user_token: str | None = None,
) -> dict[str, Any]:
    """Non-streaming chat: invoke the agent and return the final assistant reply.

    ``user_token`` is a delegated credential for the caller (see
    ``mint_delegated_token``), so the agent's NGS360 API tools act as this user.
    Omitted, the agent runs read-only.
    """
    message = latest_user_text(req)
    if not message:
        raise HTTPException(status_code=400, detail="No user message provided")

    settings = get_settings()
    thread_id = await resolve_thread(req, client, user_id)
    last_state: dict[str, Any] | None = None

    try:
        async with asyncio.timeout(NON_STREAMING_TIMEOUT_S):
            async for chunk in client.runs.stream(
                thread_id,
                settings.LANGSMITH_ASSISTANT_ID,
                input={"messages": [{"role": "user", "content": message}]},
                context=run_context,
                config=user_run_config(user_token),
                stream_mode="values",
            ):
                last_state = chunk.data
    except TimeoutError as exc:
        raise HTTPException(status_code=504, detail="Upstream chat timeout") from exc
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail=f"LangSmith invocation failed: {type(exc).__name__}",
        ) from exc

    if not last_state:
        raise HTTPException(status_code=502, detail="No state returned from LangSmith")

    # Prefer the agent's dedicated final_answer; fall back to the last assistant message.
    assistant_text = last_state.get("final_answer") or ""
    if not assistant_text:
        for msg in reversed(last_state.get("messages", [])):
            if message_role(msg) in {"assistant", "ai"}:
                assistant_text = extract_text_from_message(msg)
                break

    return {
        "thread_id": thread_id,
        "reply": assistant_text,
        "state": last_state,
    }


# ---------------------------------------------------------------------------
# 4. Streaming the answer: SSE framing and ordering
# ---------------------------------------------------------------------------


def sse_chunk(frame: ChatFrame) -> str:
    """Frame one protocol chunk as an SSE data line."""
    return f"data: {frame.model_dump_json()}\n\n"


async def stream_chat(
    req: ChatRequest,
    client,
    thread_id: str | None,
    run_context: dict[str, Any] | None = None,
    user_token: str | None = None,
) -> AsyncGenerator[str, None]:
    """Stream the agent's reply as this API's own SSE frames.

    ``messages-tuple`` yields (message_chunk, metadata) pairs. A tool call
    contributes its name; tool results and non-answer nodes contribute nothing.

    ``thread_id`` is resolved by the route so an ownership failure can be a real
    HTTP status — once the body has started, every error has to be an in-band
    error frame on a 200. It is None only when chat is unconfigured.

    ``run_context`` is likewise assembled by the route, the only place holding
    the authenticated user: this generator never sees ``CurrentUser``, so it
    cannot build a caller identity out of anything else.

    ``user_token`` is a delegated credential for the caller (see
    ``mint_delegated_token``), so the agent's NGS360 API tools act as this user.
    Omitted, the agent runs read-only.
    """
    if client is None or thread_id is None:
        yield sse_chunk(ChatFrameError(message="Chat agent is not configured"))
        return

    message = latest_user_text(req)
    if not message:
        yield sse_chunk(ChatFrameError(message="No user message provided"))
        return

    settings = get_settings()

    # First, so a client that started a new thread keeps its id if the run fails.
    yield sse_chunk(ChatFrameThread(thread_id=thread_id))

    # Last tool announced, so a streamed call's repeated argument fragments do
    # not each re-send the same name.
    status_tool = ""
    # Set by either failure path, so there is one exit below rather than three.
    error_message: str | None = None

    try:
        async with asyncio.timeout(STREAMING_TIMEOUT_S):
            async for chunk in client.runs.stream(
                thread_id,
                settings.LANGSMITH_ASSISTANT_ID,
                input={"messages": [{"role": "user", "content": message}]},
                context=run_context,
                config=user_run_config(user_token),
                stream_mode=STREAM_MODE,
            ):
                kind = stream_event_kind(getattr(chunk, "event", None))
                # A failed run is reported as a terminal event, not an
                # exception: runs.stream yields it like any other part, so
                # without this the loop would end normally and the turn would
                # report success with no answer in it.
                if kind == "error":
                    error_message = upstream_error_text(
                        getattr(chunk, "data", None)
                    )
                    break
                if kind != "messages":
                    continue
                pair = message_tuple(getattr(chunk, "data", None))
                if pair is None:
                    continue
                msg, metadata = pair

                # A tool result is the agent working, not the agent speaking.
                if is_tool_message(msg):
                    continue

                # Name the running step. With parallel calls the newest is the
                # better label, and the indicator is one line.
                names = tool_names_requested(msg)
                if names and names[-1] != status_tool:
                    status_tool = names[-1]
                    yield sse_chunk(ChatFrameStatus(tool=status_tool))

                if metadata.get("langgraph_node") != FINAL_ANSWER_NODE:
                    continue
                token = chunk_text(msg)
                if token:
                    yield sse_chunk(ChatFrameText(delta=token))
    except TimeoutError:
        error_message = "Upstream chat timeout"
    except Exception as exc:
        error_message = f"Upstream error: {str(exc).replace(chr(10), ' ')[:300]}"

    # Explicit rather than just ending the body, so the client can tell a
    # finished run from a dropped connection.
    if error_message is None:
        yield sse_chunk(ChatFrameDone())
    else:
        yield sse_chunk(ChatFrameError(message=error_message))
