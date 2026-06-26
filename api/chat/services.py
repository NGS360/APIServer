"""
Chat-related services

Streams assistant replies using the Vercel AI SDK UI Message Stream Protocol
(SSE JSON chunks terminated by [DONE]), which the frontend consumes via
useChat from @ai-sdk/react. Protocol reference:
https://ai-sdk.dev/docs/ai-sdk-ui/stream-protocol
"""

import asyncio
import json
import uuid
from typing import Any, AsyncGenerator

from api.chat.models import ChatContext

# Project the demo navigation directive falls back to when the user hasn't
# referenced one with "#".
DEMO_PROJECT_ID = "P-20260507-0008"

# Entity types the navigate directive can route to (a subset of the "#"
# reference types — these have detail pages in the app).
NAVIGABLE_TYPES = ("project", "run", "job")


def navigation_target(context: ChatContext | None) -> dict[str, str]:
    """Pick where to navigate from the entities the user referenced via "#".

    Returns the first navigable reference as ``{destination, id}``, falling back
    to the demo project when none was referenced.
    """
    if context is not None:
        for ref in context.references:
            if ref.type in NAVIGABLE_TYPES:
                return {"destination": ref.type, "id": ref.id}
    return {"destination": "project", "id": DEMO_PROJECT_ID}


def last_user_text(messages: list[dict[str, Any]]) -> str:
    """Extract the text of the most recent user message from UIMessage parts."""
    for message in reversed(messages):
        if message.get("role") == "user":
            return " ".join(
                part.get("text", "")
                for part in message.get("parts", [])
                if part.get("type") == "text"
            )
    return ""


def sse_chunk(payload: dict[str, Any]) -> str:
    """Frame one protocol chunk as an SSE data line."""
    return f"data: {json.dumps(payload)}\n\n"


async def stream_reply(
    messages: list[dict[str, Any]], user_name: str, context: ChatContext | None
) -> AsyncGenerator[str, None]:
    """
    Dispatch to a canned response based on the latest user message.

    Stands in for the in-house orchestrator: a prompt mentioning "navigate"
    streams a ``data-navigate`` UI directive to the entity the user referenced
    with "#" (or the demo project); everything else gets the text stub.
    """
    prompt = last_user_text(messages).lower()
    if "navigate" in prompt:
        async for chunk in stream_navigate_demo(navigation_target(context)):
            yield chunk
        return
    async for chunk in stream_canned_reply(prompt, user_name):
        yield chunk


async def stream_navigate_demo(target: dict[str, str]) -> AsyncGenerator[str, None]:
    """
    Canned navigation: stream a short message, then a transient ``data-navigate``
    data part the frontend consumes via useChat's onData to route the user to
    ``target`` ({destination, id}).

    This is a one-way UI directive (a data part, not a tool call): the browser
    acts on it and nothing is returned to the model, so there's no tool
    lifecycle to manage. transient=True keeps it out of saved chat history.
    """
    yield sse_chunk({"type": "start", "messageId": f"msg_{uuid.uuid4().hex}"})

    text = f"Sure — taking you to {target['destination']} {target['id']} now."
    yield sse_chunk({"type": "text-start", "id": "t1"})
    for word in text.split(" "):
        yield sse_chunk({"type": "text-delta", "id": "t1", "delta": word + " "})
        await asyncio.sleep(0.02)
    yield sse_chunk({"type": "text-end", "id": "t1"})

    yield sse_chunk(
        {"type": "data-navigate", "data": target, "transient": True}
    )

    yield sse_chunk({"type": "finish"})
    yield "data: [DONE]\n\n"


async def stream_canned_reply(prompt: str, user_name: str) -> AsyncGenerator[str, None]:
    """
    Stub generator: streams a canned reply token by token.

    TODO: replace the body of this generator with the in-house orchestrator —
    anything that yields text deltas (and later tool/source/data-* chunks)
    can be framed with sse_chunk() unchanged.
    """
    reply = (
        f"Hi {user_name}, you asked: \"{prompt}\"\n\n"
        "This is a canned streaming response from the NGS360 API. "
        "The real assistant will be able to answer questions about your "
        "projects, runs, and samples once the orchestrator is connected. "
        "Each word you see arriving individually was sent as its own "
        "text-delta chunk over SSE."
    )

    yield sse_chunk({"type": "start", "messageId": f"msg_{uuid.uuid4().hex}"})
    yield sse_chunk({"type": "text-start", "id": "t1"})
    for word in reply.split(" "):
        yield sse_chunk({"type": "text-delta", "id": "t1", "delta": word + " "})
        await asyncio.sleep(0.03)  # simulate model latency so streaming is visible
    yield sse_chunk({"type": "text-end", "id": "t1"})
    yield sse_chunk({"type": "finish"})
    yield "data: [DONE]\n\n"
