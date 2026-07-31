"""Tests for the AI Assistant chat endpoints (backed by the LangGraph agent).

The deployed agent is never contacted: a fake LangGraph client is injected via
the ``get_langgraph_client`` dependency override so the routes exercise the real
request/response and SSE framing against controllable upstream behaviour.
"""

import json
import uuid
from types import SimpleNamespace

import httpx
import pytest
from langgraph_sdk.errors import NotFoundError

from core.deps import get_langgraph_client
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


def _not_found():
    """The typed 404 the LangGraph SDK raises for a missing thread."""
    request = httpx.Request("GET", "http://langgraph.test/threads/x")
    return NotFoundError(
        "Not Found", response=httpx.Response(404, request=request), body=None
    )


class FakeThreads:
    """Fake ``client.threads`` that remembers created threads and their metadata,
    so ownership checks behave like the real API across requests."""

    def __init__(self, existing=None, get_error=None, first_messages=None, states=None):
        # thread_id -> metadata
        self.threads = dict(existing or {})
        # thread_id -> checkpointed state `values`
        self.states = dict(states or {})
        # Set to raise something other than a 404 from get(), to prove the
        # ownership check fails closed rather than treating it as "absent".
        self.get_error = get_error
        # thread_id -> the text `extract` would pull from its first message
        self.first_messages = dict(first_messages or {})

    def _matching(self, metadata):
        """Threads whose metadata is a superset of the filter, newest first.

        Insertion order stands in for creation order, so the reversal mimics
        sort_by="updated_at" / sort_order="desc".
        """
        items = [
            tid
            for tid, md in self.threads.items()
            if not metadata or all(md.get(k) == v for k, v in metadata.items())
        ]
        return list(reversed(items))

    async def search(
        self,
        metadata=None,
        limit=10,
        offset=0,
        select=None,
        extract=None,
        **kwargs,
    ):
        rows = []
        for index, tid in enumerate(self._matching(metadata)):
            row = {
                "thread_id": tid,
                "metadata": self.threads[tid],
                "created_at": f"2026-07-{28 - index:02d}T00:00:00+00:00",
                "updated_at": f"2026-07-{28 - index:02d}T12:00:00+00:00",
            }
            if extract:
                row["extracted"] = {"first_msg": self.first_messages.get(tid)}
            rows.append(row)
        end = offset + limit
        return rows[offset:end]

    async def count(self, metadata=None, **kwargs):
        return len(self._matching(metadata))

    async def create(self, thread_id=None, if_exists=None, metadata=None, **kwargs):
        tid = thread_id or "thread-123"
        self.threads.setdefault(tid, metadata or {})
        return {"thread_id": tid, "metadata": self.threads[tid]}

    async def get(self, thread_id):
        if self.get_error is not None:
            raise self.get_error
        if thread_id not in self.threads:
            raise _not_found()
        return {"thread_id": thread_id, "metadata": self.threads[thread_id]}

    async def get_state(self, thread_id):
        values = self.states.get(thread_id, {"messages": []})
        return {"thread_id": thread_id, "values": values}

    async def delete(self, thread_id):
        self.threads.pop(thread_id, None)
        self.states.pop(thread_id, None)


class FakeLangGraphClient:
    def __init__(
        self,
        tokens=None,
        final_answer="42 projects.",
        raise_exc=None,
        existing_threads=None,
        thread_get_error=None,
        first_messages=None,
        states=None,
    ):
        self.runs = FakeRuns(
            tokens if tokens is not None else ["Hello", " world"],
            final_answer,
            raise_exc=raise_exc,
        )
        self.threads = FakeThreads(
            existing_threads,
            get_error=thread_get_error,
            first_messages=first_messages,
            states=states,
        )


@pytest.fixture(name="fake_langgraph")
def fake_langgraph_fixture():
    """Override the ``get_langgraph_client`` dependency with a fake client.

    Yields a setter so a test can swap in a client with custom behaviour.
    """
    current = {"client": FakeLangGraphClient()}

    def _set(client):
        current["client"] = client
        return client

    app.dependency_overrides[get_langgraph_client] = lambda: current["client"]
    yield _set
    app.dependency_overrides.pop(get_langgraph_client, None)


TEST_USER_ID = uuid.UUID("11111111-2222-3333-4444-555555555555")
OTHER_USER_ID = uuid.UUID("99999999-8888-7777-6666-555555555555")


@pytest.fixture(name="chat_user")
def chat_user_fixture(client):
    """Pin the authenticated user's id.

    The shared ``client`` fixture builds a fresh ``User`` per request, so its
    ``uuid4`` id differs each call — which would make thread ownership fail
    between turns of the same conversation. Not autouse: it depends on the
    authenticated ``client``, so it must not reach the unauthenticated test.
    """
    from api.auth.deps import get_current_user
    from api.auth.models import User

    app.dependency_overrides[get_current_user] = lambda: User(
        id=TEST_USER_ID,
        username="testuser",
        email="test@example.com",
        is_active=True,
        is_verified=True,
    )
    yield TEST_USER_ID


def _sse_data_chunks(text):
    """Parse the JSON payloads from the SSE ``data:`` lines, excluding [DONE]."""
    lines = [line for line in text.split("\n") if line.startswith("data: ")]
    assert lines[-1] == "data: [DONE]"
    return [json.loads(line.removeprefix("data: ")) for line in lines[:-1]]


def _envelope(text="What is NGS360?", thread_id=None, chat_id="chat-1"):
    """Build the Vercel AI SDK useChat request body the frontend sends.

    ``id`` is the SDK's own conversation id and is not the thread. ``thread_id``
    is ours, attached via sendMessage's ``body``; omitting it starts a new thread.
    """
    body = {
        "id": chat_id,
        "trigger": "submit-message",
        "messages": [
            {"id": "m1", "role": "user", "parts": [{"type": "text", "text": text}]}
        ],
    }
    if thread_id is not None:
        body["thread_id"] = str(thread_id)
    return body


def test_chat_json_returns_reply(client, fake_langgraph):
    """POST /chat returns the agent's final answer as JSON."""
    response = client.post("/api/v1/chat", json=_envelope("How many projects?"))

    assert response.status_code == 200
    body = response.json()
    assert body["reply"] == "42 projects."
    assert body["state"]["executed_sql"]


def test_chat_assigns_a_thread_when_the_client_has_none(
    client, fake_langgraph, chat_user
):
    """A request with no thread_id gets a server-assigned one, like any other id."""
    fake = fake_langgraph(FakeLangGraphClient())

    body = client.post("/api/v1/chat", json=_envelope("How many?")).json()

    assigned = body["thread_id"]
    assert uuid.UUID(assigned).version == 4  # minted here, not derived from input
    assert list(fake.threads.threads) == [assigned]
    assert fake.threads.threads[assigned]["ngs360_user_id"] == str(TEST_USER_ID)


def test_chat_continues_the_thread_the_client_names(client, fake_langgraph, chat_user):
    """Later turns pass the assigned id back, and stay in the same thread."""
    fake = fake_langgraph(FakeLangGraphClient())

    first = client.post("/api/v1/chat", json=_envelope("How many?")).json()
    second = client.post(
        "/api/v1/chat", json=_envelope("And runs?", thread_id=first["thread_id"])
    ).json()

    assert second["thread_id"] == first["thread_id"]
    # Continuing must not create a second thread.
    assert len(fake.threads.threads) == 1


def test_chat_404s_for_a_thread_that_no_longer_exists(
    client, fake_langgraph, chat_user
):
    """A stale link names a thread that's gone; don't silently resurrect the id."""
    fake_langgraph(FakeLangGraphClient())

    response = client.post(
        "/api/v1/chat",
        json=_envelope("hi", thread_id="6d1f1e5c-6a5a-4c1e-9d3b-0f2a7b8c9d09"),
    )

    assert response.status_code == 404


def test_chat_rejects_a_malformed_thread_id(client, fake_langgraph, chat_user):
    """thread_id is a UUID, so garbage is a validation error, not a new thread."""
    response = client.post(
        "/api/v1/chat", json={**_envelope("hi"), "thread_id": "not-a-uuid"}
    )

    assert response.status_code == 422


def test_chat_rejects_another_users_thread(client, fake_langgraph, chat_user):
    """Appending to someone else's conversation is a 404, not a 403 (no probing)."""
    chat_id = "6d1f1e5c-6a5a-4c1e-9d3b-0f2a7b8c9d03"
    fake_langgraph(
        FakeLangGraphClient(
            existing_threads={chat_id: {"ngs360_user_id": str(OTHER_USER_ID)}}
        )
    )

    response = client.post("/api/v1/chat", json=_envelope("hi", thread_id=chat_id))

    assert response.status_code == 404


def test_chat_stream_rejects_another_users_thread(client, fake_langgraph, chat_user):
    """The stream route checks ownership before the SSE body starts, so it can 404."""
    chat_id = "6d1f1e5c-6a5a-4c1e-9d3b-0f2a7b8c9d04"
    fake_langgraph(
        FakeLangGraphClient(
            existing_threads={chat_id: {"ngs360_user_id": str(OTHER_USER_ID)}}
        )
    )

    response = client.post(
        "/api/v1/chat/stream", json=_envelope("hi", thread_id=chat_id)
    )

    assert response.status_code == 404
    assert "text/event-stream" not in response.headers.get("content-type", "")


def test_get_thread_rejects_another_users_thread(client, fake_langgraph, chat_user):
    """Raw thread state (tool output, executed SQL) is never served cross-user."""
    thread_id = "6d1f1e5c-6a5a-4c1e-9d3b-0f2a7b8c9d05"
    fake_langgraph(
        FakeLangGraphClient(
            existing_threads={thread_id: {"ngs360_user_id": str(OTHER_USER_ID)}}
        )
    )

    response = client.get(f"/api/v1/chat/threads/{thread_id}")

    assert response.status_code == 404


def test_get_thread_returns_state_for_owner(client, fake_langgraph, chat_user):
    """The owner still gets their own thread state."""
    thread_id = "6d1f1e5c-6a5a-4c1e-9d3b-0f2a7b8c9d06"
    fake_langgraph(
        FakeLangGraphClient(
            existing_threads={thread_id: {"ngs360_user_id": str(TEST_USER_ID)}}
        )
    )

    response = client.get(f"/api/v1/chat/threads/{thread_id}")

    assert response.status_code == 200
    assert response.json()["thread_id"] == thread_id


def test_get_thread_rejects_unowned_legacy_thread(client, fake_langgraph, chat_user):
    """Threads created before ownership was recorded are unreachable, not public."""
    thread_id = "6d1f1e5c-6a5a-4c1e-9d3b-0f2a7b8c9d07"
    fake_langgraph(FakeLangGraphClient(existing_threads={thread_id: {}}))

    response = client.get(f"/api/v1/chat/threads/{thread_id}")

    assert response.status_code == 404


def test_chat_fails_closed_when_ownership_cannot_be_checked(
    client, fake_langgraph, chat_user
):
    """A non-404 from the thread lookup must not be read as "no such thread".

    Otherwise a transient upstream error would fall through to the idempotent
    create, which returns the existing thread — handing over someone else's
    conversation.
    """
    fake_langgraph(
        FakeLangGraphClient(thread_get_error=RuntimeError("upstream unavailable"))
    )

    response = client.post(
        "/api/v1/chat",
        json=_envelope("hi", thread_id="6d1f1e5c-6a5a-4c1e-9d3b-0f2a7b8c9d08"),
    )

    assert response.status_code == 502


def _owned(user_id=None):
    return {"ngs360_user_id": str(user_id or TEST_USER_ID)}


def test_list_threads_returns_only_the_callers_own(
    client, fake_langgraph, chat_user
):
    """Listing is filtered by the owner recorded in thread metadata."""
    fake_langgraph(
        FakeLangGraphClient(
            existing_threads={
                "aaa": _owned(),
                "bbb": _owned(OTHER_USER_ID),
                "ccc": _owned(),
                "ddd": {},  # legacy thread with no owner
            },
            first_messages={"aaa": "How many projects?", "ccc": "Which runs failed?"},
        )
    )

    response = client.get("/api/v1/chat/threads")

    assert response.status_code == 200
    body = response.json()
    assert [c["id"] for c in body["data"]] == ["ccc", "aaa"]  # newest first
    assert body["total_items"] == 2


def test_list_threads_titles_come_from_the_first_message(
    client, fake_langgraph, chat_user
):
    """No title is stored: it's derived from the conversation's first message."""
    long_question = "Which sequencing runs failed QC in the last quarter of the year?"
    fake_langgraph(
        FakeLangGraphClient(
            existing_threads={"aaa": _owned(), "bbb": _owned(), "ccc": _owned()},
            first_messages={"aaa": long_question, "bbb": "Summarize a project"},
        )
    )

    by_id = {c["id"]: c["title"] for c in client.get("/api/v1/chat/threads").json()["data"]}

    assert by_id["bbb"] == "Summarize a project"
    # Truncated at 48 chars with an ellipsis, as the UI used to do locally.
    assert by_id["aaa"] == "Which sequencing runs failed QC in the last quar…"
    assert len(by_id["aaa"]) == 49 and by_id["aaa"].endswith("…")
    # A thread with nothing extractable is still listed, so paging stays honest.
    assert by_id["ccc"] == "New chat"


def test_list_threads_prefers_a_title_override(client, fake_langgraph, chat_user):
    """A stored title wins over the derived one, ready for renaming."""
    fake_langgraph(
        FakeLangGraphClient(
            existing_threads={
                "aaa": {**_owned(), "ngs360_title": "Q3 QC review"},
            },
            first_messages={"aaa": "Which runs failed QC?"},
        )
    )

    body = client.get("/api/v1/chat/threads").json()

    assert body["data"][0]["title"] == "Q3 QC review"


def test_list_threads_paginates(client, fake_langgraph, chat_user):
    """Pagination metadata matches the other list endpoints in this API."""
    fake_langgraph(
        FakeLangGraphClient(
            existing_threads={f"t{i}": _owned() for i in range(5)},
            first_messages={f"t{i}": f"question {i}" for i in range(5)},
        )
    )

    first = client.get("/api/v1/chat/threads?skip=0&limit=2").json()
    assert [c["id"] for c in first["data"]] == ["t4", "t3"]
    assert (first["total_items"], first["total_pages"]) == (5, 3)
    assert (first["current_page"], first["per_page"]) == (1, 2)
    assert (first["has_next"], first["has_prev"]) == (True, False)

    last = client.get("/api/v1/chat/threads?skip=4&limit=2").json()
    assert [c["id"] for c in last["data"]] == ["t0"]
    assert (last["current_page"], last["has_next"], last["has_prev"]) == (3, False, True)


def test_list_threads_requires_auth(unauthenticated_client, fake_langgraph):
    """Conversation titles are user data — no listing without a caller."""
    assert unauthenticated_client.get("/api/v1/chat/threads").status_code == 401


def test_list_threads_never_requests_transcripts(
    client, fake_langgraph, chat_user
):
    """The list must not select `values`, or every page would ship whole transcripts."""
    fake = fake_langgraph(
        FakeLangGraphClient(
            existing_threads={"aaa": _owned()}, first_messages={"aaa": "hi"}
        )
    )
    calls = []
    original_search = fake.threads.search

    async def recording_search(**kwargs):
        calls.append(kwargs)
        return await original_search(**kwargs)

    fake.threads.search = recording_search

    client.get("/api/v1/chat/threads")

    assert calls, "search was not called"
    assert "values" not in (calls[0]["select"] or [])
    assert calls[0]["metadata"] == {"ngs360_user_id": str(TEST_USER_ID)}


# A thread's stored state as LangGraph really shapes it: `type` (not `role`),
# tool-call steps as empty-content `ai` messages, and raw tool output.
LANGGRAPH_STATE = {
    "messages": [
        {"type": "human", "id": "h1", "content": "How many projects?"},
        {"type": "ai", "id": "a1", "content": "", "tool_calls": [{"name": "sql"}]},
        {"type": "tool", "id": "t1", "content": "11013", "name": "sql"},
        {"type": "ai", "id": "a2", "content": "There are **11,013 projects**."},
        {"type": "human", "id": "h2", "content": "And runs?"},
        {"type": "ai", "id": "a3", "content": "There are 412 runs."},
    ],
    "final_answer": "There are 412 runs.",
    "executed_sql": ["SELECT COUNT(*) FROM projects"],
}


def test_get_thread_messages_returns_only_the_visible_transcript(
    client, fake_langgraph, chat_user
):
    """Tool calls and raw query output are dropped, so a reload matches the UI."""
    fake_langgraph(
        FakeLangGraphClient(
            existing_threads={"aaa": _owned()},
            states={"aaa": LANGGRAPH_STATE},
        )
    )

    response = client.get("/api/v1/chat/threads/aaa/messages")

    assert response.status_code == 200
    body = response.json()
    assert [(m["role"], m["parts"][0]["text"]) for m in body["messages"]] == [
        ("user", "How many projects?"),
        ("assistant", "There are **11,013 projects**."),
        ("user", "And runs?"),
        ("assistant", "There are 412 runs."),
    ]
    # The empty tool-call step, the tool output and executed_sql never surface.
    assert "11013" not in response.text
    assert "SELECT COUNT" not in response.text


def test_get_thread_messages_shape_matches_the_chat_ui(client, fake_langgraph, chat_user):
    """Messages come back as AI SDK UIMessages so they can be replayed directly."""
    fake_langgraph(
        FakeLangGraphClient(
            existing_threads={"aaa": _owned()}, states={"aaa": LANGGRAPH_STATE}
        )
    )

    body = client.get("/api/v1/chat/threads/aaa/messages").json()

    assert body["thread_id"] == "aaa"
    first = body["messages"][0]
    assert set(first) == {"id", "role", "parts"}
    assert first["parts"] == [{"type": "text", "text": "How many projects?"}]


def test_get_thread_messages_rejects_another_users_thread(
    client, fake_langgraph, chat_user
):
    fake_langgraph(
        FakeLangGraphClient(
            existing_threads={"aaa": _owned(OTHER_USER_ID)},
            states={"aaa": LANGGRAPH_STATE},
        )
    )

    assert client.get("/api/v1/chat/threads/aaa/messages").status_code == 404


def test_get_thread_messages_404s_for_a_missing_thread(
    client, fake_langgraph, chat_user
):
    fake_langgraph(FakeLangGraphClient())

    assert client.get("/api/v1/chat/threads/nope/messages").status_code == 404


def test_get_thread_messages_handles_an_empty_thread(client, fake_langgraph, chat_user):
    """A thread whose first turn failed returns no messages, not an error."""
    fake_langgraph(
        FakeLangGraphClient(existing_threads={"aaa": _owned()}, states={"aaa": {}})
    )

    body = client.get("/api/v1/chat/threads/aaa/messages").json()

    assert body["messages"] == []


def test_delete_thread_removes_it(client, fake_langgraph, chat_user):
    """Deleting a conversation removes the thread, so the agent forgets it too."""
    fake = fake_langgraph(
        FakeLangGraphClient(existing_threads={"aaa": _owned(), "bbb": _owned()})
    )

    response = client.delete("/api/v1/chat/threads/aaa")

    assert response.status_code == 204
    assert set(fake.threads.threads) == {"bbb"}


def test_delete_thread_rejects_another_users(client, fake_langgraph, chat_user):
    """You cannot delete someone else's conversation."""
    fake = fake_langgraph(
        FakeLangGraphClient(existing_threads={"aaa": _owned(OTHER_USER_ID)})
    )

    assert client.delete("/api/v1/chat/threads/aaa").status_code == 404
    assert "aaa" in fake.threads.threads


def test_delete_all_threads_only_touches_the_callers(
    client, fake_langgraph, chat_user
):
    """Clear-all is scoped to the caller and leaves other users' threads alone."""
    fake = fake_langgraph(
        FakeLangGraphClient(
            existing_threads={
                "mine1": _owned(),
                "mine2": _owned(),
                "theirs": _owned(OTHER_USER_ID),
                "legacy": {},
            }
        )
    )

    response = client.delete("/api/v1/chat/threads")

    assert response.status_code == 204
    assert set(fake.threads.threads) == {"theirs", "legacy"}


def test_chat_stream_emits_vercel_protocol(client, fake_langgraph):
    """POST /chat/stream emits the Vercel UI Message Stream over SSE."""
    fake_langgraph(FakeLangGraphClient(tokens=["What ", "is ", "NGS360?"]))

    response = client.post("/api/v1/chat/stream", json=_envelope("hi"))

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert response.headers["x-vercel-ai-ui-message-stream"] == "v1"

    chunks = _sse_data_chunks(response.text)
    types = [c["type"] for c in chunks]
    assert types[0] == "start"
    assert chunks[0]["messageId"].startswith("msg_")
    # The assigned thread id comes before any text, so the client still learns it
    # if the run fails midway.
    assert types[1] == "data-thread"
    assert types[2] == "text-start"
    assert types[-2] == "text-end"
    assert types[-1] == "finish"
    assert all(t == "text-delta" for t in types[3:-2])

    text = "".join(c["delta"] for c in chunks if c["type"] == "text-delta")
    # Only the final-answer node's tokens are forwarded; the intermediate
    # "tools" node output is filtered out.
    assert text == "What is NGS360?"
    assert "raw tool output" not in text


def test_chat_stream_announces_the_assigned_thread(client, fake_langgraph, chat_user):
    """The client can only learn a server-assigned thread id from the stream."""
    fake = fake_langgraph(FakeLangGraphClient())

    response = client.post("/api/v1/chat/stream", json=_envelope("hi"))

    announced = [
        c for c in _sse_data_chunks(response.text) if c["type"] == "data-thread"
    ]
    assert len(announced) == 1
    thread_id = announced[0]["data"]["thread_id"]
    # It names the thread that was actually created for this turn.
    assert list(fake.threads.threads) == [thread_id]


def test_chat_stream_announces_the_thread_the_client_named(
    client, fake_langgraph, chat_user
):
    """Continuing a conversation echoes the same id back, so the client can trust it."""
    thread_id = "6d1f1e5c-6a5a-4c1e-9d3b-0f2a7b8c9d0a"
    fake_langgraph(FakeLangGraphClient(existing_threads={thread_id: _owned()}))

    response = client.post(
        "/api/v1/chat/stream", json=_envelope("hi", thread_id=thread_id)
    )

    announced = [
        c for c in _sse_data_chunks(response.text) if c["type"] == "data-thread"
    ]
    assert announced[0]["data"]["thread_id"] == thread_id


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


def test_get_thread_state(client, fake_langgraph, chat_user):
    """GET /chat/threads/{id} returns the thread state for its owner."""
    fake_langgraph(
        FakeLangGraphClient(
            existing_threads={"thread-123": {"ngs360_user_id": str(TEST_USER_ID)}}
        )
    )
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
