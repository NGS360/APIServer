"""
Local tester for the AI Assistant chat endpoint.

Drives the same `api.chat.services.stream_reply` generator the `/chat` route
uses, parses the Vercel AI SDK UI Message Stream chunks it emits, and renders
the streamed text and tool/navigate events in the terminal. Requires the LLM
gateway settings (LLM_BASE_URL, LLM_API_KEY, LLM_MODEL) in `.env`.

Usage:
    # interactive REPL (keeps conversation history)
    python scripts/test_chat.py

    # one-shot: send a single prompt and exit
    python scripts/test_chat.py "Take me to run R-2024-01"

REPL commands:
    /reset    start a new conversation
    /quit     exit (also: Ctrl-D)
"""

import asyncio
import json
import sys
import uuid
from typing import Any

# Ensure the project root is importable when run as `python scripts/test_chat.py`.
sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent))

from api.chat.services import stream_reply  # noqa: E402


def user_message(text: str) -> dict[str, Any]:
    """Build a UIMessage in the shape the frontend sends."""
    return {
        "id": f"msg_{uuid.uuid4().hex}",
        "role": "user",
        "parts": [{"type": "text", "text": text}],
    }


def assistant_message(text: str) -> dict[str, Any]:
    return {
        "id": f"msg_{uuid.uuid4().hex}",
        "role": "assistant",
        "parts": [{"type": "text", "text": text}],
    }


async def send(messages: list[dict[str, Any]]) -> str:
    """Stream one assistant turn, print it live, and return the assembled text."""
    reply = ""
    print("assistant> ", end="", flush=True)
    async for line in stream_reply(messages, "local-tester", None):
        if not line.startswith("data: "):
            continue
        payload = line[len("data: "):].strip()
        if payload == "[DONE]":
            break
        chunk = json.loads(payload)
        kind = chunk.get("type")
        if kind == "text-delta":
            delta = chunk.get("delta", "")
            reply += delta
            print(delta, end="", flush=True)
        elif kind == "data-navigate":
            data = chunk.get("data", {})
            print(f"\n  [navigate → {data.get('destination')} {data.get('id')}]", end="", flush=True)
    print()  # newline after the turn
    return reply


async def one_shot(prompt: str) -> None:
    await send([user_message(prompt)])


async def repl() -> None:
    print("NGS360 chat tester — type a message, /reset to clear, /quit to exit.\n")
    messages: list[dict[str, Any]] = []
    while True:
        try:
            text = input("you> ").strip()
        except EOFError:
            print()
            break
        if not text:
            continue
        if text in ("/quit", "/exit"):
            break
        if text == "/reset":
            messages = []
            print("(conversation reset)\n")
            continue
        messages.append(user_message(text))
        reply = await send(messages)
        messages.append(assistant_message(reply))
        print()


def main() -> None:
    if len(sys.argv) > 1:
        asyncio.run(one_shot(" ".join(sys.argv[1:])))
    else:
        asyncio.run(repl())


if __name__ == "__main__":
    main()
