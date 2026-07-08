"""
Chat-related services

Streams assistant replies using the Vercel AI SDK UI Message Stream Protocol
(SSE JSON chunks terminated by [DONE]), which the frontend consumes via
useChat from @ai-sdk/react. Protocol reference:
https://ai-sdk.dev/docs/ai-sdk-ui/stream-protocol

The reply is produced by a LangGraph ReAct agent (backed by a Claude model).
The agent runs the model -> tool -> model loop; we
translate its event stream into the SSE chunks the frontend expects.
"""

import json
import uuid
from typing import Any, AsyncGenerator

from langchain_anthropic import ChatAnthropic
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain.agents import create_agent

from api.chat.models import ChatContext
from api.chat.tools import TOOLS
from core.config import get_settings

SYSTEM_PROMPT = (
    "You are the NGS360 assistant. You help users work with their genomics "
    "projects, runs, samples, and jobs. Use the navigate tool when the user "
    "asks to open or go to a specific entity, and use lookup tools to ground "
    "your answers in real data rather than guessing. Be concise and direct."
)


def sse_chunk(payload: dict[str, Any]) -> str:
    """Frame one protocol chunk as an SSE data line."""
    return f"data: {json.dumps(payload)}\n\n"


def message_text(message: dict[str, Any]) -> str:
    """Join the text parts of a single UIMessage."""
    return " ".join(
        part.get("text", "")
        for part in message.get("parts", [])
        if part.get("type") == "text"
    ).strip()


def last_user_text(messages: list[dict[str, Any]]) -> str:
    """Extract the text of the most recent user message from UIMessage parts."""
    for message in reversed(messages):
        if message.get("role") == "user":
            return message_text(message)
    return ""


def context_note(context: ChatContext | None) -> str:
    """Render the page/entity context the user attached into a system note."""
    if context is None:
        return ""
    parts: list[str] = []
    if context.page is not None:
        parts.append(f"The user is currently viewing {context.page.type} {context.page.id}.")
    if context.references:
        refs = ", ".join(f"{ref.type} {ref.id}" for ref in context.references)
        parts.append(f"The user referenced: {refs}.")
    return " ".join(parts)


def to_lc_messages(
    messages: list[dict[str, Any]], context: ChatContext | None
) -> list[Any]:
    """Convert the UIMessage history into LangChain messages, with a system prompt."""
    system = SYSTEM_PROMPT
    note = context_note(context)
    if note:
        system = f"{system}\n\n{note}"

    lc_messages: list[Any] = [SystemMessage(system)]
    for message in messages:
        text = message_text(message)
        if not text:
            continue
        role = message.get("role")
        if role == "user":
            lc_messages.append(HumanMessage(text))
        elif role == "assistant":
            lc_messages.append(AIMessage(text))
    return lc_messages


def build_agent():
    """Construct a ReAct agent (backed by Claude)."""
    settings = get_settings()
    llm = ChatAnthropic(
        model=settings.LLM_MODEL,
        base_url=f"{settings.LLM_BASE_URL}/anthropic",
        api_key=settings.LLM_API_KEY,
        timeout=300,
        max_tokens=8000,
        streaming=True,
    )
    return create_agent(llm, TOOLS)


def _delta_text(chunk: Any) -> str:
    """Extract streamable text from an AIMessageChunk (str or content-block list)."""
    content = getattr(chunk, "content", "")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(
            block.get("text", "")
            for block in content
            if isinstance(block, dict) and block.get("type") == "text"
        )
    return ""


async def stream_reply(
    messages: list[dict[str, Any]], user_name: str, context: ChatContext | None
) -> AsyncGenerator[str, None]:
    """
    Run the agent and stream its reply as UI Message Stream chunks.

    Text deltas from the model become ``text-delta`` chunks; when the agent
    calls the ``navigate`` tool, a transient ``data-navigate`` part is emitted
    for the frontend's useChat onData handler to act on.
    """
    agent = build_agent()
    lc_messages = to_lc_messages(messages, context)

    text_id = "t1"
    yield sse_chunk({"type": "start", "messageId": f"msg_{uuid.uuid4().hex}"})
    yield sse_chunk({"type": "text-start", "id": text_id})

    async for event in agent.astream_events({"messages": lc_messages}, version="v2"):
        kind = event["event"]

        if kind == "on_chat_model_stream":
            delta = _delta_text(event["data"]["chunk"])
            if delta:
                yield sse_chunk({"type": "text-delta", "id": text_id, "delta": delta})

        elif kind == "on_tool_end" and event.get("name") == "navigate":
            tool_input = event["data"].get("input", {})
            destination = tool_input.get("destination")
            entity_id = tool_input.get("id")
            if destination and entity_id:
                yield sse_chunk(
                    {
                        "type": "data-navigate",
                        "data": {"destination": destination, "id": entity_id},
                        "transient": True,
                    }
                )

    yield sse_chunk({"type": "text-end", "id": text_id})
    yield sse_chunk({"type": "finish"})
    yield "data: [DONE]\n\n"
