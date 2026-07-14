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
from typing import Any, AsyncGenerator

from fastapi import HTTPException

from api.chat.models import ChatRequest
from core.config import get_settings

# Wall-clock ceilings for a single upstream invocation.
NON_STREAMING_TIMEOUT_S = 60
STREAMING_TIMEOUT_S = 120

# The agent graph streams tokens from multiple nodes; only this node produces
# the user-facing answer. Tokens from other nodes (e.g. the "tools" node's raw
# SQL results) are intermediate reasoning and are not forwarded to the UI.
FINAL_ANSWER_NODE = "reasoning"


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


async def _resolve_thread_id(req: ChatRequest, client) -> str:
    """Return the request's thread id, creating a new thread when absent."""
    if req.thread_id:
        return req.thread_id
    thread = await client.threads.create()
    return thread["thread_id"]


async def run_chat(req: ChatRequest, client) -> dict[str, Any]:
    """Non-streaming chat: invoke the agent and return the final assistant reply."""
    if client is None:
        raise HTTPException(status_code=502, detail="Chat agent is not configured")

    settings = get_settings()
    thread_id = await _resolve_thread_id(req, client)
    last_state: dict[str, Any] | None = None

    try:
        async with asyncio.timeout(NON_STREAMING_TIMEOUT_S):
            async for chunk in client.runs.stream(
                thread_id,
                settings.LANGSMITH_ASSISTANT_ID,
                input={"messages": [{"role": "user", "content": req.message}]},
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
    req: ChatRequest, client
) -> AsyncGenerator[str, None]:
    """
    Stream the agent's reply framed as the Vercel AI SDK UI Message Stream
    protocol, so the frontend's useChat hook consumes it unchanged.

    LangGraph's ``messages-tuple`` stream yields (message_chunk, metadata) token
    pairs; each token is reframed as a ``text-delta`` chunk.
    """
    if client is None:
        yield sse_chunk({"type": "start", "messageId": f"msg_{uuid.uuid4().hex}"})
        yield sse_chunk(
            {"type": "error", "errorText": "Chat agent is not configured"}
        )
        yield "data: [DONE]\n\n"
        return

    settings = get_settings()

    yield sse_chunk({"type": "start", "messageId": f"msg_{uuid.uuid4().hex}"})
    yield sse_chunk({"type": "text-start", "id": "t1"})

    try:
        thread_id = await _resolve_thread_id(req, client)
        async with asyncio.timeout(STREAMING_TIMEOUT_S):
            async for chunk in client.runs.stream(
                thread_id,
                settings.LANGSMITH_ASSISTANT_ID,
                input={"messages": [{"role": "user", "content": req.message}]},
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
