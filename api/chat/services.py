"""
Chat-related services

Invokes the deployed NGS360 SQL Agent (LangGraph Platform) and adapts its token
stream into the Vercel AI SDK UI Message Stream Protocol (SSE JSON chunks
terminated by [DONE]), which the frontend consumes via useChat from
@ai-sdk/react. Protocol reference:
https://ai-sdk.dev/docs/ai-sdk-ui/stream-protocol
"""

import asyncio
import json
import uuid
from datetime import datetime, timezone
from typing import Any, AsyncGenerator

from fastapi import HTTPException
from langgraph_sdk.errors import NotFoundError

from api.chat.models import ChatRequest
from core.config import get_settings

# Wall-clock ceilings for a single upstream invocation.
NON_STREAMING_TIMEOUT_S = 60
STREAMING_TIMEOUT_S = 120

# The agent graph streams tokens from multiple nodes; only this node produces
# the user-facing answer. Tokens from other nodes (e.g. the "tools" node's raw
# SQL results) are intermediate reasoning and are not forwarded to the UI.
FINAL_ANSWER_NODE = "reasoning"

# Stream part carrying the thread id back to the client. "data-*" is the AI SDK's
# channel for application data alongside the reply; the client validates it in
# lib/chat-directives.ts.
THREAD_DATA_PART = "data-thread"

# Thread metadata key recording which user owns a thread. New thread ids are
# assigned here, but continuing a conversation means naming one, so this is what
# stops an authenticated user reaching someone else's — see verify_thread_owner.
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


def sse_chunk(payload: dict[str, Any]) -> str:
    """Frame one protocol chunk as an SSE data line."""
    return f"data: {json.dumps(payload)}\n\n"


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


def latest_user_text(req: ChatRequest) -> str:
    """Concatenate the text parts of the most recent user message.

    Scanning ``messages`` in reverse handles both the ``submit-message`` and
    ``regenerate-message`` triggers, since the last user turn is always present.
    """
    for msg in reversed(req.messages):
        if msg.role == "user":
            return "".join(p.text for p in msg.parts if p.type == "text" and p.text)
    return ""


async def get_owned_thread(
    client, thread_id: str, user_id: str
) -> dict[str, Any] | None:
    """Fetch ``thread_id`` if ``user_id`` owns it.

    Returns the thread if it exists and is theirs, None if it doesn't exist yet.
    Raises 404 — not 403 — when it belongs to someone else, so probing can't
    distinguish "not yours" from "not there".

    This matters because every route that reads or continues a thread takes the id
    from the caller: without the check, an authenticated user who learned another
    user's thread id could read that conversation, or append a turn to it and read
    the answer back.

    Only a genuine 404 counts as "doesn't exist". Swallowing every error here
    would fail open — a transient upstream blip would look like an absent thread,
    and callers treat that as "safe to proceed".
    """
    try:
        thread = await client.threads.get(thread_id)
    except NotFoundError:
        return None
    except Exception as exc:
        raise HTTPException(
            status_code=502, detail="Could not verify thread ownership"
        ) from exc

    metadata = (thread or {}).get("metadata") or {}
    if metadata.get(OWNER_METADATA_KEY) != user_id:
        raise HTTPException(status_code=404, detail="Thread not found")
    return thread


async def verify_thread_owner(client, thread_id: str, user_id: str) -> bool:
    """Whether ``user_id`` owns an existing ``thread_id``. See get_owned_thread."""
    return await get_owned_thread(client, thread_id, user_id) is not None


async def resolve_thread(req: ChatRequest, client, user_id: str) -> str:
    """Return the thread this turn belongs to, creating one if the client has none.

    Thread ids are assigned here, like every other id in this API, rather than
    accepted from the client. A request that names a thread is continuing one, so
    it must pass the ownership check; naming a thread that's gone (a stale link,
    say) is a 404 and the client starts a new chat rather than silently resurrect
    the id.
    """
    if req.thread_id is not None:
        thread_id = str(req.thread_id)
        if not await verify_thread_owner(client, thread_id, user_id):
            raise HTTPException(status_code=404, detail="Thread not found")
        return thread_id

    thread_id = str(uuid.uuid4())
    await client.threads.create(
        thread_id=thread_id,
        metadata={
            OWNER_METADATA_KEY: user_id,
            "ngs360_created_at": datetime.now(timezone.utc).isoformat(),
        },
    )
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

    Reads straight from the agent's thread store, filtered by the owner recorded
    in thread metadata — there is no local table, so this is the only place the
    user/thread association lives.
    """
    if client is None:
        raise HTTPException(status_code=502, detail="Chat agent is not configured")

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


def _message_role(msg: dict[str, Any]) -> str:
    """Normalize a stored message's role. LangGraph uses ``type``; tests use ``role``."""
    return str(msg.get("role", msg.get("type", ""))).lower()


def transcript_from_state(state: dict[str, Any]) -> list[dict[str, Any]]:
    """Rebuild the visible conversation from a thread's checkpointed state.

    Stored state holds the agent's whole working history — tool calls and raw
    tool output included — but the UI only ever saw the final answers. Two kinds
    of message are dropped to reproduce what was on screen:

    * ``tool`` messages, which are raw query output.
    * ``ai`` messages with empty content, which are the tool-call steps.

    That leaves the content-bearing ``ai`` messages, which come from the same
    node the live stream forwards (FINAL_ANSWER_NODE). If the graph ever grows
    another node that emits text, this would start showing messages that never
    appeared in the stream — worth revisiting alongside any graph change.
    """
    messages: list[dict[str, Any]] = []
    for msg in state.get("messages") or []:
        if not isinstance(msg, dict):
            continue
        role = _message_role(msg)
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


async def get_thread_messages(
    client, thread_id: str, user_id: str
) -> dict[str, Any]:
    """The caller's thread as the user saw it: its transcript as UIMessages."""
    if client is None:
        raise HTTPException(status_code=502, detail="Chat agent is not configured")

    if await get_owned_thread(client, thread_id, user_id) is None:
        raise HTTPException(status_code=404, detail="Thread not found")

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


async def delete_thread(client, thread_id: str, user_id: str) -> None:
    """Delete one of the caller's chat threads, agent memory included."""
    if client is None:
        raise HTTPException(status_code=502, detail="Chat agent is not configured")

    if await get_owned_thread(client, thread_id, user_id) is None:
        raise HTTPException(status_code=404, detail="Thread not found")

    try:
        await client.threads.delete(thread_id)
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Thread delete failed: {type(exc).__name__}",
        ) from exc


async def delete_all_threads(client, user_id: str) -> int:
    """Delete every chat thread belonging to the caller. Returns the count.

    Pages through the owner's threads rather than trusting one search page, so
    "clear all" doesn't quietly leave older ones behind.
    """
    if client is None:
        raise HTTPException(status_code=502, detail="Chat agent is not configured")

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


async def run_chat(req: ChatRequest, client, user_id: str) -> dict[str, Any]:
    """Non-streaming chat: invoke the agent and return the final assistant reply."""
    if client is None:
        raise HTTPException(status_code=502, detail="Chat agent is not configured")

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
            role = str(msg.get("role", msg.get("type", ""))).lower()
            if role in {"assistant", "ai"}:
                assistant_text = extract_text_from_message(msg)
                break

    return {
        "thread_id": thread_id,
        "reply": assistant_text,
        "state": last_state,
    }


async def stream_chat_vercel(
    req: ChatRequest, client, thread_id: str | None
) -> AsyncGenerator[str, None]:
    """
    Stream the agent's reply framed as the Vercel AI SDK UI Message Stream
    protocol, so the frontend's useChat hook consumes it unchanged.

    LangGraph's ``messages-tuple`` stream yields (message_chunk, metadata) token
    pairs; each token is reframed as a ``text-delta`` chunk.

    ``thread_id`` is resolved by the route so an ownership failure can be a real
    HTTP status; once the SSE body has started, every error has to be an in-band
    error chunk on a 200. It is None only when chat is unconfigured, which the
    first branch below already covers.
    """
    if client is None or thread_id is None:
        yield sse_chunk({"type": "start", "messageId": f"msg_{uuid.uuid4().hex}"})
        yield sse_chunk(
            {"type": "error", "errorText": "Chat agent is not configured"}
        )
        yield "data: [DONE]\n\n"
        return

    message = latest_user_text(req)
    if not message:
        yield sse_chunk({"type": "start", "messageId": f"msg_{uuid.uuid4().hex}"})
        yield sse_chunk({"type": "error", "errorText": "No user message provided"})
        yield "data: [DONE]\n\n"
        return

    settings = get_settings()

    yield sse_chunk({"type": "start", "messageId": f"msg_{uuid.uuid4().hex}"})
    # Tell the client which thread this turn belongs to. It's the only way it can
    # learn the id of a thread the server just created, and it goes out before
    # any text so the client still has it if the run fails midway.
    yield sse_chunk({"type": THREAD_DATA_PART, "data": {"thread_id": thread_id}})
    yield sse_chunk({"type": "text-start", "id": "t1"})

    try:
        async with asyncio.timeout(STREAMING_TIMEOUT_S):
            async for chunk in client.runs.stream(
                thread_id,
                settings.LANGSMITH_ASSISTANT_ID,
                input={"messages": [{"role": "user", "content": message}]},
                stream_mode="messages-tuple",
            ):
                if chunk.event != "messages":
                    continue
                message_chunk, metadata = chunk.data
                # Only forward the final answer node's tokens; skip intermediate
                # reasoning/tool output so it doesn't bleed into the UI.
                if metadata.get("langgraph_node") != FINAL_ANSWER_NODE:
                    continue
                token = message_chunk.get("content")
                if token:
                    yield sse_chunk(
                        {"type": "text-delta", "id": "t1", "delta": token}
                    )
        yield sse_chunk({"type": "text-end", "id": "t1"})
        yield sse_chunk({"type": "finish"})
    except TimeoutError:
        yield sse_chunk({"type": "text-end", "id": "t1"})
        yield sse_chunk({"type": "error", "errorText": "Upstream chat timeout"})
    except Exception as exc:
        safe_detail = str(exc).replace("\n", " ")[:300]
        yield sse_chunk({"type": "text-end", "id": "t1"})
        yield sse_chunk(
            {"type": "error", "errorText": f"Upstream error: {safe_detail}"}
        )

    yield "data: [DONE]\n\n"
