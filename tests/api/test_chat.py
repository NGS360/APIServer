"""Tests for the AI Assistant chat streaming endpoint."""

import json
import uuid
from types import SimpleNamespace

import pytest

from main import app


class FakeRuns:
    """Fake ``client.runs`` whose ``stream`` mimics the LangGraph SDK.

    ``values`` mode yields whole-state chunks; ``messages-tuple`` mode yields
    (message_chunk, metadata) token pairs under the ``messages`` event.
    """

    def __init__(self, tokens, final_answer, raise_exc=None):
        self.tokens = tokens
        self.final_answer = final_answer
        self.raise_exc = raise_exc

    async def stream(self, thread_id, assistant_id, input, stream_mode):
        if self.raise_exc is not None:
            raise self.raise_exc
        if stream_mode == "values":
            full_text = "".join(self.tokens)
            state = {
                "messages": [
                    {"role": "user", "content": input["messages"][0]["content"]},
                    {"role": "assistant", "content": full_text},
                ],
                "final_answer": self.final_answer,
                "executed_sql": ["SELECT COUNT(*) FROM projects"],
            }
            yield SimpleNamespace(event="values", data=state)
        elif stream_mode == "messages-tuple":
            # An intermediate tool-node token that must be filtered out.
            yield SimpleNamespace(
                event="messages",
                data=({"content": "raw tool output"}, {"langgraph_node": "tools"}),
            )
            for token in self.tokens:
                yield SimpleNamespace(
                    event="messages",
                    data=({"content": token}, {"langgraph_node": "reasoning"}),
                )
        else:  # pragma: no cover - defensive
            raise ValueError(f"unexpected stream_mode {stream_mode}")


class FakeThreads:
    async def create(self, thread_id=None, if_exists=None, **kwargs):
        # The chat id is supplied as thread_id (idempotent create); echo it back.
        return {"thread_id": thread_id or "thread-123"}

    async def get_state(self, thread_id):
        return {"thread_id": thread_id, "values": {"messages": []}}


class FakeLangGraphClient:
    def __init__(self, tokens=None, final_answer="42 projects.", raise_exc=None):
        self.runs = FakeRuns(
            tokens if tokens is not None else ["Hello", " world"],
            final_answer,
            raise_exc=raise_exc,
        )
        self.threads = FakeThreads()


@pytest.fixture(name="fake_langgraph")
def fake_langgraph_fixture():
    """Install a fake LangGraph client on app.state for the duration of a test.

    Yields a setter so a test can swap in a client with custom behaviour.
    """
    original = getattr(app.state, "langgraph", None)

    def _set(client):
        app.state.langgraph = client
        return client

    _set(FakeLangGraphClient())
    yield _set
    app.state.langgraph = original


def _sse_data_chunks(text):
    """Parse the JSON payloads from the SSE ``data:`` lines, excluding [DONE]."""
    lines = [line for line in text.split("\n") if line.startswith("data: ")]
    assert lines[-1] == "data: [DONE]"
    return [json.loads(line.removeprefix("data: ")) for line in lines[:-1]]


def _expected_thread_id(chat_id):
    """The thread UUID the service derives from a chat id (mirrors services.py)."""
    from api.chat.services import THREAD_NAMESPACE

    return str(uuid.uuid5(THREAD_NAMESPACE, chat_id))


def _envelope(text="What is NGS360?", chat_id="chat-1"):
    """Build the Vercel AI SDK useChat request body the frontend sends."""
    return {
        "id": chat_id,
        "trigger": "submit-message",
        "messages": [
            {"id": "m1", "role": "user", "parts": [{"type": "text", "text": text}]}
        ],
    }


def test_chat_json_returns_reply(client, fake_langgraph):
    """POST /chat returns the agent's final answer as JSON."""
    response = client.post(
        "/api/v1/chat", json=_envelope("How many projects?", chat_id="chat-1")
    )

    assert response.status_code == 200
    body = response.json()
    # The chat id maps to a deterministic thread UUID.
    assert body["thread_id"] == _expected_thread_id("chat-1")
    assert body["reply"] == "42 projects."
    assert body["state"]["executed_sql"]


def test_chat_json_uses_chat_id_as_thread(client, fake_langgraph):
    """The stable chat id maps to a stable thread UUID for multi-turn continuity."""
    thread = _expected_thread_id("conv-42")
    first = client.post("/api/v1/chat", json=_envelope("How many?", chat_id="conv-42"))
    second = client.post("/api/v1/chat", json=_envelope("And runs?", chat_id="conv-42"))
    assert first.json()["thread_id"] == thread
    # Same chat id -> same thread on the follow-up (deterministic, no round-trip).
    assert second.json()["thread_id"] == thread


def test_chat_stream_emits_vercel_protocol(client, fake_langgraph):
    """POST /chat/stream emits the Vercel UI Message Stream over SSE."""
    fake_langgraph(FakeLangGraphClient(tokens=["What ", "is ", "NGS360?"]))

    response = client.post("/api/v1/chat/stream", json=_envelope("hi"))

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert response.headers["x-vercel-ai-ui-message-stream"] == "v1"

    lines = [line for line in response.text.split("\n") if line.startswith("data: ")]
    assert lines[-1] == "data: [DONE]"

    chunks = [json.loads(line.removeprefix("data: ")) for line in lines[:-1]]
    types = [chunk["type"] for chunk in chunks]
    assert types[0] == "start"
    assert chunks[0]["messageId"].startswith("msg_")
    assert types[1] == "text-start"
    assert types[-2] == "text-end"
    assert types[-1] == "finish"
    assert all(t == "text-delta" for t in types[2:-2])

    text = "".join(c["delta"] for c in chunks if c["type"] == "text-delta")
    assert "What is NGS360?" in text
    assert "testuser" in text


def test_chat_stream_reports_upstream_error(client, fake_langgraph):
    """An upstream failure is surfaced as an error chunk, still ending in [DONE]."""
    fake_langgraph(FakeLangGraphClient(raise_exc=RuntimeError("boom")))

    response = client.post("/api/v1/chat/stream", json=_envelope("hi"))

    assert response.status_code == 200
    chunks = _sse_data_chunks(response.text)
    assert any(c["type"] == "error" for c in chunks)


def test_chat_json_upstream_error_returns_502(client, fake_langgraph):
    """A non-streaming upstream failure maps to a 502."""
    fake_langgraph(FakeLangGraphClient(raise_exc=RuntimeError("boom")))

    response = client.post("/api/v1/chat", json=_envelope("hi"))
    assert response.status_code == 502


def test_get_thread_state(client, fake_langgraph):
    """GET /chat/threads/{id} returns the thread state."""
    response = client.get("/api/v1/chat/threads/thread-123")
    assert response.status_code == 200
    assert response.json()["thread_id"] == "thread-123"


def test_chat_requires_auth(unauthenticated_client, fake_langgraph):
    response = unauthenticated_client.post("/api/v1/chat", json=_envelope())
    assert response.status_code == 401


def test_chat_rejects_missing_messages(client, fake_langgraph):
    """An envelope with no messages is rejected by schema validation (422)."""
    response = client.post("/api/v1/chat", json={"id": "chat-1", "messages": []})
    assert response.status_code == 422


def test_chat_rejects_empty_user_text(client, fake_langgraph):
    """An envelope whose user message has no text yields a 400 empty-message guard."""
    response = client.post(
        "/api/v1/chat",
        json={
            "id": "chat-1",
            "messages": [{"id": "m1", "role": "user", "parts": []}],
        },
    )
    assert response.status_code == 400
