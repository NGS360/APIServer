"""Tests for the AI Assistant chat endpoints (backed by the LangGraph agent).

The deployed agent is never contacted: a fake LangGraph client is injected via
the ``get_langgraph_client`` dependency override so the routes exercise the real
request/response and SSE framing against controllable upstream behaviour.
"""

import asyncio
import json
import uuid
from types import SimpleNamespace

import httpx
import pytest
from langgraph_sdk.errors import InternalServerError, NotFoundError

from api.chat.models import MAX_CONTEXT_REFERENCES
from core.deps import get_langgraph_client
from main import app


class FakeRuns:
    """Fake ``client.runs`` whose ``stream`` mimics the LangGraph SDK.

    ``values`` mode yields whole-state chunks; ``messages-tuple`` mode yields the
    (message_chunk, metadata) token pairs under the ``messages`` event.

    ``script`` replaces the default (one filtered-out intermediate token, then
    the answer's tokens) so a test can stage tool calls and tool results in a
    chosen order — which the stream is expected to render as nothing at all.
    ``hang_s`` sleeps before finishing, for the timeout path.
    """

    def __init__(
        self, tokens, final_answer, raise_exc=None, script=None, hang_s=None
    ):
        self.tokens = tokens
        self.final_answer = final_answer
        self.raise_exc = raise_exc
        self.script = script
        self.hang_s = hang_s
        # Every stream_mode the route asked for, so a test can assert on it.
        self.stream_modes = []
        # Every runtime context the route sent, likewise. None is recorded as
        # passed: "sent nothing" differs from "sent an empty context".
        self.contexts = []
        # Every run config the route passed, so a test can assert the caller's
        # own credential is what the agent runs with.
        self.configs = []

    @property
    def stream_mode(self):
        """The single mode the streaming route asked for."""
        return self.stream_modes[-1] if self.stream_modes else None

    @property
    def context(self):
        """The runtime context the last run was given."""
        return self.contexts[-1] if self.contexts else None

    @property
    def config(self):
        """The run config of the last run started."""
        return self.configs[-1] if self.configs else None

    def _default_script(self):
        """Today's behaviour: an intermediate token, then the answer."""
        return [
            # An intermediate reasoning token that must not reach the answer.
            _message_event("raw tool output", node="tools"),
            *[_message_event(token) for token in self.tokens],
        ]

    async def stream(
        self, thread_id, assistant_id, input, stream_mode, context=None, config=None
    ):
        self.stream_modes.append(stream_mode)
        self.contexts.append(context)
        self.configs.append(config)
        if self.raise_exc is not None:
            raise self.raise_exc
        modes = stream_mode if isinstance(stream_mode, list) else [stream_mode]
        if "messages-tuple" in modes:
            for event in self.script if self.script is not None else self._default_script():
                yield event
            if self.hang_s is not None:
                await asyncio.sleep(self.hang_s)
        elif "values" in modes:
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
        else:  # pragma: no cover - defensive
            raise ValueError(f"unexpected stream_mode {stream_mode}")


def _message_event(content, node="reasoning", event="messages", **message):
    """One ``messages-tuple`` chunk: a message dict plus its node metadata."""
    return SimpleNamespace(
        event=event,
        data=({"content": content, **message}, {"langgraph_node": node}),
    )


def _tool_call_event(name, args, call_id="call_1", node="reasoning", message_id="ai-1"):
    """An assistant message that asks for a tool call, whole rather than streamed."""
    return _message_event(
        "",
        node=node,
        id=message_id,
        tool_calls=[{"name": name, "args": args, "id": call_id}],
    )


def _tool_result_event(content, call_id="call_1", name="sql", status="success"):
    """A ToolMessage carrying that call's result, as the tools node emits it."""
    return _message_event(
        content,
        node="tools",
        type="tool",
        name=name,
        tool_call_id=call_id,
        status=status,
    )


def _not_found():
    """The typed 404 the LangGraph SDK raises for a missing thread."""
    request = httpx.Request("GET", "http://langgraph.test/threads/x")
    return NotFoundError(
        "Not Found", response=httpx.Response(404, request=request), body=None
    )


def _unavailable():
    """What the SDK raises when the deployment is down (a 503 reaches us as this)."""
    request = httpx.Request("POST", "http://langgraph.test/threads")
    return InternalServerError(
        "503 Service Temporarily Unavailable",
        response=httpx.Response(503, request=request),
        body=None,
    )


class FakeThreads:
    """Fake ``client.threads`` that remembers created threads and their metadata,
    so ownership checks behave like the real API across requests."""

    def __init__(
        self,
        existing=None,
        get_error=None,
        first_messages=None,
        states=None,
        create_error=None,
        search_error=None,
    ):
        # thread_id -> metadata
        self.threads = dict(existing or {})
        # thread_id -> checkpointed state `values`
        self.states = dict(states or {})
        # Set to raise something other than a 404 from get(), to prove the
        # ownership check fails closed rather than treating it as "absent".
        self.get_error = get_error
        # Set to make create()/search() fail, standing in for a down deployment.
        self.create_error = create_error
        self.search_error = search_error
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
        if self.search_error is not None:
            raise self.search_error
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
        if self.create_error is not None:
            raise self.create_error
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
        thread_create_error=None,
        thread_search_error=None,
        script=None,
        hang_s=None,
    ):
        self.runs = FakeRuns(
            tokens if tokens is not None else ["Hello", " world"],
            final_answer,
            raise_exc=raise_exc,
            script=script,
            hang_s=hang_s,
        )
        self.threads = FakeThreads(
            existing_threads,
            get_error=thread_get_error,
            first_messages=first_messages,
            states=states,
            create_error=thread_create_error,
            search_error=thread_search_error,
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
    """Parse the JSON payloads from the SSE ``data:`` lines.

    Every run ends with a ``done`` or an ``error`` frame — explicitly, rather
    than by the body just stopping, so the client can tell a finished run from a
    dropped connection. That is asserted here so no individual test has to.
    """
    lines = [line for line in text.split("\n") if line.startswith("data: ")]
    chunks = [json.loads(line.removeprefix("data: ")) for line in lines]
    assert chunks[-1]["type"] in {"done", "error"}, chunks[-1]
    return chunks


def _envelope(text="What is NGS360?", thread_id=None, chat_id="chat-1", context=None):
    """Build the Vercel AI SDK useChat request body the frontend sends.

    ``id`` is the SDK's own conversation id and is not the thread. ``thread_id``
    and ``context`` are ours, attached via sendMessage's ``body``; omitting the
    thread id starts a new thread.
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
    if context is not None:
        body["context"] = context
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


def test_chat_stream_emits_this_apis_own_frames_over_sse(client, fake_langgraph):
    """POST /chat/stream emits our frames, not the AI SDK's.

    The browser does consume the SDK's UI Message Stream protocol, but the
    mapping is the client transport's job, so nothing here is named for it: no
    `start`, no text-start/text-end pairing, no x-vercel header.
    """
    fake_langgraph(FakeLangGraphClient(tokens=["What ", "is ", "NGS360?"]))

    response = client.post("/api/v1/chat/stream", json=_envelope("hi"))

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert "x-vercel-ai-ui-message-stream" not in response.headers

    chunks = _sse_data_chunks(response.text)
    types = [c["type"] for c in chunks]
    # The thread id comes first, so the client still learns it if the run fails
    # midway; then text; then exactly one terminal frame.
    assert types[0] == "thread"
    assert types[-1] == "done"
    assert all(t == "text" for t in types[1:-1])

    text = "".join(c["delta"] for c in chunks if c["type"] == "text")
    # Only the final-answer node's tokens are forwarded; the intermediate
    # "tools" node output is filtered out.
    assert text == "What is NGS360?"
    assert "raw tool output" not in text


def test_chat_stream_announces_the_assigned_thread(client, fake_langgraph, chat_user):
    """The client can only learn a server-assigned thread id from the stream."""
    fake = fake_langgraph(FakeLangGraphClient())

    response = client.post("/api/v1/chat/stream", json=_envelope("hi"))

    announced = [
        c for c in _sse_data_chunks(response.text) if c["type"] == "thread"
    ]
    assert len(announced) == 1
    thread_id = announced[0]["thread_id"]
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
        c for c in _sse_data_chunks(response.text) if c["type"] == "thread"
    ]
    assert announced[0]["thread_id"] == thread_id


def test_chat_stream_reports_upstream_error(client, fake_langgraph):
    """An upstream failure is surfaced as an error chunk, as the run's terminal frame."""
    fake_langgraph(FakeLangGraphClient(raise_exc=RuntimeError("boom")))

    response = client.post("/api/v1/chat/stream", json=_envelope("hi"))

    assert response.status_code == 200
    chunks = _sse_data_chunks(response.text)
    assert any(c["type"] == "error" for c in chunks)


# --- The agent runs as the caller, not as a service account ------------------
#
# The agent's NGS360 API tools inherit the caller's own permissions, which only
# works if the caller's raw credential reaches the run. It travels on the run
# config under a key whose exact name is load-bearing: LangGraph keeps `__`-
# prefixed configurable keys out of checkpoint metadata, and keys containing
# "token" out of LangSmith traces. Renaming it would start persisting user
# credentials, so the name is asserted literally here rather than imported.


USER_TOKEN_KEY = "__ngs360_user_token"
BEARER = "a-user-jwt"


def _auth():
    return {"Authorization": f"Bearer {BEARER}"}


def test_chat_json_runs_as_the_calling_user(client, fake_langgraph):
    """The caller's own bearer token is what the agent's API tools act with."""
    fake = fake_langgraph(FakeLangGraphClient())

    response = client.post(
        "/api/v1/chat", json=_envelope("How many projects?"), headers=_auth()
    )

    assert response.status_code == 200
    assert fake.runs.config == {"configurable": {USER_TOKEN_KEY: BEARER}}


def test_chat_stream_runs_as_the_calling_user(client, fake_langgraph):
    """The streaming route forwards the credential too, not just the JSON one."""
    fake = fake_langgraph(FakeLangGraphClient())

    response = client.post(
        "/api/v1/chat/stream", json=_envelope("hi"), headers=_auth()
    )

    assert response.status_code == 200
    _sse_data_chunks(response.text)  # drain the body so the run completes
    assert fake.runs.config == {"configurable": {USER_TOKEN_KEY: BEARER}}


def test_an_api_key_is_forwarded_verbatim(client, fake_langgraph):
    """An ngs360_ API key is a credential the NGS360 API accepts, so replay it as-is.

    Nothing here inspects or rewrites the credential — CurrentUser on the same
    route has already rejected the request if it is not good.
    """
    fake = fake_langgraph(FakeLangGraphClient())

    client.post(
        "/api/v1/chat",
        json=_envelope("hi"),
        headers={"Authorization": "Bearer ngs360_abc123"},
    )

    assert fake.runs.config["configurable"][USER_TOKEN_KEY] == "ngs360_abc123"


@pytest.mark.parametrize("path", ["/api/v1/chat", "/api/v1/chat/stream"])
def test_no_credential_means_no_config_at_all(client, fake_langgraph, path):
    """With nothing to forward, the agent gets no config and stays read-only.

    Not an empty string: the agent treats a present-but-empty token as no token
    anyway, and passing one would make the run config claim a user it cannot name.
    """
    fake = fake_langgraph(FakeLangGraphClient())

    response = client.post(path, json=_envelope("hi"))

    assert response.status_code == 200
    if path.endswith("/stream"):
        _sse_data_chunks(response.text)
    assert fake.runs.config is None


@pytest.mark.parametrize("credential", [None, ""])
def test_user_run_config_treats_an_absent_credential_as_no_config(credential):
    """Directly, so the empty-string case is pinned and not only implied."""
    from api.chat.services import user_run_config

    assert user_run_config(credential) is None


def test_the_token_travels_only_on_the_run_config(client, fake_langgraph):
    """It must not reach thread metadata, which is persisted unencrypted.

    The run config is in LangGraph Platform's at-rest encryption set; thread
    metadata is not, and it is what the ownership check reads back on every turn.
    """
    fake = fake_langgraph(FakeLangGraphClient())

    client.post("/api/v1/chat", json=_envelope("hi"), headers=_auth())

    assert BEARER not in json.dumps(fake.threads.threads)


@pytest.mark.parametrize("path", ["/api/v1/chat", "/api/v1/chat/stream"])
def test_the_credential_and_the_context_reach_one_run_together(
    client, fake_langgraph, path
):
    """Two independent channels on the same call: neither displaces the other.

    The credential rides `config`; the caller identity and attached context ride
    `context`. Both must arrive on every run.

    The credential must not appear in `context`: it authorizes the agent's API
    calls and is not part of describing who is asking.
    """
    fake = fake_langgraph(FakeLangGraphClient())

    response = client.post(path, json=_envelope("hi"), headers=_auth())

    assert response.status_code == 200
    if path.endswith("/stream"):
        _sse_data_chunks(response.text)
    assert fake.runs.config == {"configurable": {USER_TOKEN_KEY: BEARER}}
    assert fake.runs.context["caller"]["username"] == "testuser"
    assert BEARER not in json.dumps(fake.runs.context)


# --- The agent's tool work is invisible, except for the names ----------------
#
# The volume of tool detail the agent produces is overwhelming, so none of its
# CONTENT reaches the user. The one thing that does cross is a tool's NAME, on a
# status frame, so the working indicator can say which step is running.
#
# That is the whole boundary, and it is what these tests guard: names yes,
# arguments and results never. A test that starts asserting a tool's content on
# the wire is a sign the boundary is being reopened by accident.

# Tool payloads copied verbatim off the live dev graph (thread
# fbd16cae-4d4e-5d00-a9e9-ec5bc9bd6f73, read 2026-08-03). Kept real because what
# matters is that nothing about them — not the "ERROR: " prefix, not the row
# data, not the echoed SQL — can leak into the answer.
REAL_QUERY_FAILURE = (
    "ERROR: Query failed: MySQL Error: 1146 (42S02): Table 'ngs360.fileentity' "
    "doesn't exist\nPlease fix the query and try again."
)
REAL_QUERY_SUCCESS = (
    "SQL executed:\n  SELECT * FROM sequencingrun LIMIT 1\n\n"
    "Showing rows 1-1 of 1 total:\n\n"
    "id                               | status\n"
    "------------------------------------------\n"
    "000dd8e3ddd74900aead83e57681999a | READY "
)

# Every frame type the stream is allowed to emit.
ANSWER_FRAMES = {
    "thread",
    "status",
    "text",
    "done",
    "error",
}


def _stream_chunks(client, **envelope):
    """POST to the streaming route and parse its protocol chunks."""
    response = client.post("/api/v1/chat/stream", json=_envelope(**envelope))
    assert response.status_code == 200
    return _sse_data_chunks(response.text)


def test_chat_stream_asks_upstream_only_for_message_tokens(client, fake_langgraph):
    """One stream mode. The answer's tokens are all this endpoint reads.

    Pinned because the second mode an earlier revision asked for ("updates")
    existed solely to carry the graph's executed_sql to the UI. Re-adding a mode
    means re-opening that decision.
    """
    fake = fake_langgraph(FakeLangGraphClient())

    _stream_chunks(client, text="hi")

    assert fake.runs.stream_mode == "messages-tuple"


def test_chat_stream_forwards_a_tool_name_but_none_of_its_content(
    client, fake_langgraph
):
    """The name reaches the client; the query it ran and the rows it got do not."""
    fake_langgraph(
        FakeLangGraphClient(
            script=[
                _tool_call_event(
                    "query_database", {"sql": "SELECT COUNT(*) FROM project"}
                ),
                _tool_result_event("11013", name="query_database"),
                _message_event("There are "),
                _message_event("11,013."),
            ]
        )
    )

    chunks = _stream_chunks(client, text="how many?")

    assert [c["type"] for c in chunks] == [
        "thread",
        "status",
        "text",
        "text",
        "done",
    ]
    status = next(c for c in chunks if c["type"] == "status")
    assert status["tool"] == "query_database"
    # The name and nothing else — no part id, no SDK framing. Giving the status
    # a stable part id so it rewrites one line is the transport's job now.
    assert set(status) == {"type", "tool"}
    # The answer, and not one character of the tool's arguments or output.
    assert "".join(c["delta"] for c in chunks if c["type"] == "text") == (
        "There are 11,013."
    )
    assert "11013" not in str(chunks)
    assert "SELECT COUNT(*)" not in str(chunks)


def test_chat_stream_reports_each_tool_in_the_order_they_run(
    client, fake_langgraph
):
    """One status frame per tool, so the indicator tracks the agent's progress."""
    fake_langgraph(
        FakeLangGraphClient(
            script=[
                _tool_call_event("list_tables", {}, call_id="c1"),
                _tool_result_event("project, sample", name="list_tables"),
                _tool_call_event(
                    "get_table_schema", {"table": "project"},
                    call_id="c2", message_id="ai-2",
                ),
                _tool_result_event("id, name", name="get_table_schema"),
                _message_event("Two tables."),
            ]
        )
    )

    chunks = _stream_chunks(client, text="what tables?")

    assert [
        c["tool"] for c in chunks if c["type"] == "status"
    ] == ["list_tables", "get_table_schema"]


def test_chat_stream_does_not_report_a_tool_result_as_a_new_step(
    client, fake_langgraph
):
    """Only calls move the indicator. A result is the step finishing, not starting.

    The result message carries the same tool name, so without the call/result
    distinction every tool would be announced twice.
    """
    fake_langgraph(
        FakeLangGraphClient(
            script=[
                _tool_call_event("list_tables", {}),
                _tool_result_event("project, sample", name="list_tables"),
                _message_event("Two."),
            ]
        )
    )

    chunks = _stream_chunks(client, text="what tables?")

    assert len([c for c in chunks if c["type"] == "status"]) == 1


def test_chat_stream_skips_a_tool_call_that_has_no_usable_name(
    client, fake_langgraph
):
    """An unnamed call leaves the previous label up rather than blanking it.

    The name comes from a graph we don't own, so it may be missing or junk. A
    blank status would clear the indicator's detail line mid-run, which reads as
    the agent having stopped; keeping the last real label is the better failure.
    """
    fake_langgraph(
        FakeLangGraphClient(
            script=[
                _tool_call_event("list_tables", {}, call_id="c1"),
                # Neither of these names a tool.
                _message_event(
                    "", id="ai-2", tool_calls=[{"args": {}, "id": "c2"}]
                ),
                _message_event(
                    "", id="ai-3", tool_calls=[{"name": "  ", "args": {}, "id": "c3"}]
                ),
                _message_event("Done."),
            ]
        )
    )

    chunks = _stream_chunks(client, text="what tables?")

    assert [
        c["tool"] for c in chunks if c["type"] == "status"
    ] == ["list_tables"]


def test_chat_stream_leaks_no_frame_type_outside_the_answer_contract(
    client, fake_langgraph
):
    """Whatever the graph does, only the seven answer frames go out.

    Broad on purpose: a tool frame, reasoning part or step marker added back by
    accident fails here rather than surfacing in the UI.
    """
    fake_langgraph(
        FakeLangGraphClient(
            script=[
                _tool_call_event("list_tables", {}),
                _tool_result_event("project, sample, file", name="list_tables"),
                _tool_call_event(
                    "query_database",
                    {"sql": "SELECT 1"},
                    call_id="c2",
                    message_id="ai-2",
                ),
                _tool_result_event(
                    REAL_QUERY_SUCCESS, call_id="c2", name="query_database"
                ),
                # A failure, which an earlier revision turned into a
                # tool-output-error frame.
                _tool_call_event(
                    "query_database",
                    {"sql": "SELECT * FROM fileentity"},
                    call_id="c3",
                    message_id="ai-3",
                ),
                _tool_result_event(
                    REAL_QUERY_FAILURE, call_id="c3", name="query_database"
                ),
                _message_event("One run is READY."),
            ]
        )
    )

    chunks = _stream_chunks(client, text="tell me about runs")

    assert {c["type"] for c in chunks} <= ANSWER_FRAMES
    assert not any(c["type"].startswith("tool-") for c in chunks)
    assert not any(c["type"].startswith("data-executed") for c in chunks)
    # Not even the error text of a failed tool call reaches the client.
    assert "fileentity" not in str(chunks)
    assert "ERROR:" not in str(chunks)


def test_chat_stream_announces_a_streamed_tool_call_once(client, fake_langgraph):
    """Argument fragments are dropped, and the call is announced a single time.

    A streamed AIMessageChunk carries ``tool_call_chunks`` rather than
    ``tool_calls``, arriving as a run of fragments of which only the first names
    the tool. Without the dedupe the indicator would be rewritten on every
    fragment, and the arguments those fragments carry must not escape either.
    """
    fake_langgraph(
        FakeLangGraphClient(
            script=[
                _message_event(
                    "",
                    id="ai-1",
                    tool_call_chunks=[
                        {
                            "name": "query_database",
                            "args": '{"sql": "SEL',
                            "id": "call_c",
                            "index": 0,
                        },
                    ],
                ),
                _message_event(
                    "",
                    id="ai-1",
                    tool_call_chunks=[
                        {"name": None, "args": 'ECT 1"}', "id": None, "index": 0},
                    ],
                ),
                _message_event("Just one."),
            ]
        )
    )

    chunks = _stream_chunks(client, text="one?")

    assert [c["type"] for c in chunks] == [
        "thread",
        "status",
        "text",
        "done",
    ]
    status = next(c for c in chunks if c["type"] == "status")
    assert status["tool"] == "query_database"
    assert "SELECT" not in str(chunks)


def test_chat_stream_drops_a_tool_result_routed_through_the_answer_node(
    client, fake_langgraph
):
    """The node filter alone would not catch this one.

    A tool result whose metadata says it came from the answer node is still a
    tool result. Without the tool-message guard its raw rows would be spliced
    into the reply as though the agent had said them.
    """
    fake_langgraph(
        FakeLangGraphClient(
            script=[
                _message_event(
                    "raw rows the user must never see",
                    node="reasoning",
                    type="tool",
                    tool_call_id="call_a",
                    name="query_database",
                ),
                _message_event("Two runs failed QC."),
            ]
        )
    )

    chunks = _stream_chunks(client, text="what failed?")

    text = "".join(c["delta"] for c in chunks if c["type"] == "text")
    assert text == "Two runs failed QC."
    assert "raw rows" not in str(chunks)


def test_chat_stream_keeps_intermediate_reasoning_out_of_the_answer(
    client, fake_langgraph
):
    """Text from a node other than the answer node is not the answer."""
    fake_langgraph(
        FakeLangGraphClient(
            script=[
                _message_event("I should count the projects", node="planner"),
                _message_event("There are 11,013."),
            ]
        )
    )

    chunks = _stream_chunks(client, text="how many?")

    text = "".join(c["delta"] for c in chunks if c["type"] == "text")
    assert text == "There are 11,013."
    assert "I should count" not in str(chunks)


def test_chat_stream_never_splices_a_tool_use_block_into_the_answer(
    client, fake_langgraph
):
    """Multi-modal content carries tool_use blocks beside the text.

    Only the text blocks become deltas — stringifying a block we don't
    understand would put a serialized tool call in the middle of the reply.
    """
    fake_langgraph(
        FakeLangGraphClient(
            script=[
                _message_event(
                    [
                        {"type": "text", "text": "Checking"},
                        {
                            "type": "tool_use",
                            "name": "query_database",
                            "input": {"sql": "SELECT 1"},
                        },
                        {"type": "text", "text": " now."},
                    ]
                ),
            ]
        )
    )

    chunks = _stream_chunks(client, text="hi")

    assert "".join(c["delta"] for c in chunks if c["type"] == "text") == (
        "Checking now."
    )
    assert "tool_use" not in str(chunks)
    assert "SELECT 1" not in str(chunks)


# --- The working indicator depends on when text starts -----------------------
#
# The client gets no frame telling it the agent is busy; it infers that from
# having an assistant message with no text yet. So the first text frame is the
# boundary between "Thinking…" and the answer, and these pin both sides of it.


def test_chat_stream_sends_no_text_before_the_agent_speaks(client, fake_langgraph):
    """No text frame reaches the client during the tool phase.

    Any text at all would end the working indicator immediately, while the agent
    still had all its tool calls to make.
    """
    fake_langgraph(
        FakeLangGraphClient(
            script=[
                _tool_call_event("query_database", {"sql": "SELECT 1"}),
                _tool_result_event("1", name="query_database"),
                _message_event("One."),
            ]
        )
    )

    types = [c["type"] for c in _stream_chunks(client, text="hi")]

    # No text at all until the agent actually speaks, so the client has an
    # assistant message with no text for the whole tool phase — which is what it
    # renders the indicator for.
    assert types[0] == "thread"
    assert types.index("text") > types.index("status")
    assert types[-1] == "done"


def test_chat_stream_omits_the_text_part_when_the_turn_had_no_text(
    client, fake_langgraph
):
    """A turn that produced no answer text has no text part at all, not an empty one."""
    fake_langgraph(
        FakeLangGraphClient(
            script=[
                _tool_call_event("query_database", {"sql": "SELECT 1"}),
                _tool_result_event("1", name="query_database"),
            ]
        )
    )

    types = [c["type"] for c in _stream_chunks(client, text="hi")]

    assert types == ["thread", "status", "done"]


def test_chat_stream_timeout_before_any_text_still_terminates(
    client, fake_langgraph, monkeypatch
):
    """Timing out mid-tool ends the run with an error frame and no text."""
    from api.chat import services

    monkeypatch.setattr(services, "STREAMING_TIMEOUT_S", 0.05)
    fake_langgraph(
        FakeLangGraphClient(
            script=[_tool_call_event("query_database", {"sql": "SELECT 1"})],
            hang_s=5,
        )
    )

    chunks = _stream_chunks(client, text="hi")

    assert [c["type"] for c in chunks] == [
        "thread",
        "status",
        "error",
    ]
    assert chunks[-1]["message"] == "Upstream chat timeout"


def test_chat_stream_timeout_closes_a_text_part_it_opened(
    client, fake_langgraph, monkeypatch
):
    """Timing out mid-answer keeps the text already sent and then errors."""
    from api.chat import services

    monkeypatch.setattr(services, "STREAMING_TIMEOUT_S", 0.05)
    fake_langgraph(
        FakeLangGraphClient(script=[_message_event("Half an ans")], hang_s=5)
    )

    types = [c["type"] for c in _stream_chunks(client, text="hi")]

    assert types == [
        "thread",
        "text",
        "error",
    ]


def test_chat_stream_upstream_failure_before_any_text_terminates(
    client, fake_langgraph
):
    """The generic failure path also ends in exactly one error frame."""
    fake_langgraph(FakeLangGraphClient(raise_exc=RuntimeError("boom")))

    types = [c["type"] for c in _stream_chunks(client, text="hi")]

    assert types == ["thread", "error"]


def test_chat_stream_reports_an_upstream_error_event_as_a_failure(
    client, fake_langgraph
):
    """A failed run ends in an error frame, not done.

    LangGraph reports a failed run as a terminal "error" stream event rather
    than by raising, so runs.stream yields it like any other part. Without the
    check the loop would end normally and the turn would claim success while
    carrying no answer.
    """
    fake_langgraph(
        FakeLangGraphClient(
            script=[
                SimpleNamespace(
                    event="error",
                    data={
                        "error": "GraphRecursionError",
                        "message": "Recursion limit of 25 reached",
                    },
                ),
            ]
        )
    )

    chunks = _stream_chunks(client, text="hi")

    assert [c["type"] for c in chunks] == ["thread", "error"]
    assert chunks[-1]["message"] == "Upstream error: Recursion limit of 25 reached"


def test_chat_stream_stops_reading_after_an_upstream_error(client, fake_langgraph):
    """The error is terminal: text already sent stays, nothing after it is read."""
    fake_langgraph(
        FakeLangGraphClient(
            script=[
                _message_event("Half an ans"),
                SimpleNamespace(event="error", data={"message": "upstream exploded"}),
                # Anything the graph emits after failing is not the answer.
                _message_event("wer that never arrives"),
            ]
        )
    )

    chunks = _stream_chunks(client, text="hi")

    assert [c["type"] for c in chunks] == ["thread", "text", "error"]
    assert chunks[1]["delta"] == "Half an ans"
    assert "never arrives" not in str(chunks)


def test_chat_stream_error_event_without_a_usable_message_still_reports(
    client, fake_langgraph
):
    """The payload shape is the graph's, so an unusable one still says something."""
    fake_langgraph(
        FakeLangGraphClient(script=[SimpleNamespace(event="error", data=None)])
    )

    chunks = _stream_chunks(client, text="hi")

    assert chunks[-1] == {"type": "error", "message": "Upstream error"}


def test_chat_stream_ignores_stream_events_it_does_not_understand(
    client, fake_langgraph
):
    """Unknown or reshaped upstream events are skipped, not unpacked blindly.

    A subgraph namespaces the event name and the messages modes are sometimes
    suffixed, so a chunk that isn't the shape we expect must not raise
    mid-stream.
    """
    fake_langgraph(
        FakeLangGraphClient(
            script=[
                SimpleNamespace(event="metadata", data={"run_id": "r1"}),
                # A messages event whose payload is not a (message, metadata) pair.
                SimpleNamespace(event="messages/metadata", data={"r1": {}}),
                SimpleNamespace(
                    event="updates", data={"sql": {"executed_sql": ["Q"]}}
                ),
                # The namespaced form a subgraph produces.
                _message_event("ok", event="sub:1|messages"),
            ]
        )
    )

    chunks = _stream_chunks(client, text="hi")

    assert [c["type"] for c in chunks] == [
        "thread",
        "text",
        "done",
    ]


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


# --- The runtime context sent with every run --------------------------------
#
# What the user attached travels as LangGraph runtime context: per-run, not in
# the message text and not in graph state. Two origins meet here, and these
# tests keep them apart — page and references are whatever the browser sent,
# the caller must be unforgeable from the body.
#
# The failure mode they guard against: an agent that does not declare a
# context_schema drops an unknown context silently, so a wrong key name errors
# nowhere. Only a test can tell us the payload still has the shape it reads.


def test_chat_sends_the_attached_context_to_the_agent(client, fake_langgraph):
    fake = fake_langgraph(FakeLangGraphClient())

    client.post(
        "/api/v1/chat",
        json=_envelope(
            "how many samples?",
            context={
                "page": {"type": "project", "id": "P-20230314-0004"},
                "references": [{"type": "run", "id": "R-2"}],
            },
        ),
    )

    context = fake.runs.context
    assert context["page"] == {"type": "project", "id": "P-20230314-0004"}
    assert context["references"] == [{"type": "run", "id": "R-2"}]


def test_chat_stream_sends_the_attached_context_to_the_agent(client, fake_langgraph):
    """Both routes, because the streaming one is the only one the UI uses."""
    fake = fake_langgraph(FakeLangGraphClient())

    _stream_chunks(
        client,
        text="how many samples?",
        context={"page": {"type": "project", "id": "P-20230314-0004"}},
    )

    assert fake.runs.context["page"] == {"type": "project", "id": "P-20230314-0004"}


def test_chat_names_the_authenticated_caller(client, fake_langgraph, chat_user):
    """Who is asking is added server-side, on every run."""
    fake = fake_langgraph(FakeLangGraphClient())

    client.post("/api/v1/chat", json=_envelope("how many projects?"))

    assert fake.runs.context["caller"] == {
        "user_id": str(TEST_USER_ID),
        "username": "testuser",
    }


def test_chat_sends_the_caller_even_with_nothing_attached(client, fake_langgraph):
    """No chips is not the same as no context — "my projects" still needs the user."""
    fake = fake_langgraph(FakeLangGraphClient())

    client.post("/api/v1/chat", json=_envelope("how many projects?"))

    assert fake.runs.context is not None
    assert "caller" in fake.runs.context
    assert "page" not in fake.runs.context
    assert "references" not in fake.runs.context


def test_chat_ignores_a_caller_supplied_in_the_body(client, fake_langgraph, chat_user):
    """The decisive one: a body-supplied caller would let any authenticated user
    claim to be anyone else, which is worse than sending no identity at all."""
    fake = fake_langgraph(FakeLangGraphClient())

    client.post(
        "/api/v1/chat",
        json=_envelope(
            "how many projects?",
            context={
                "caller": {"user_id": str(OTHER_USER_ID), "username": "someone-else"},
                "page": {"type": "project", "id": "P-20230314-0004"},
            },
        ),
    )

    assert fake.runs.context["caller"] == {
        "user_id": str(TEST_USER_ID),
        "username": "testuser",
    }


def test_caller_matches_the_thread_owner(client, fake_langgraph, chat_user):
    """One truth, two homes: thread metadata records the owner, context the
    asker. Both come from the same user in the same request, so a disagreement
    between them is a bug rather than a state to tolerate."""
    fake = fake_langgraph(FakeLangGraphClient())

    response = client.post("/api/v1/chat", json=_envelope("how many projects?"))

    thread_id = response.json()["thread_id"]
    owner = fake.threads.threads[thread_id]["ngs360_user_id"]
    assert fake.runs.context["caller"]["user_id"] == owner


def test_chat_forwards_a_samples_project(client, fake_langgraph):
    """A sample id is unique only within a project, so it travels with one."""
    fake = fake_langgraph(FakeLangGraphClient())

    client.post(
        "/api/v1/chat",
        json=_envelope(
            "tell me about it",
            context={
                "references": [
                    {"type": "sample", "id": "S-9", "project_id": "P-20230314-0004"}
                ]
            },
        ),
    )

    assert fake.runs.context["references"] == [
        {"type": "sample", "id": "S-9", "project_id": "P-20230314-0004"}
    ]


def test_chat_rejects_an_unknown_entity_type(client, fake_langgraph):
    """An unknown kind is a 422 here rather than a surprise at the agent."""
    response = client.post(
        "/api/v1/chat",
        json=_envelope(context={"page": {"type": "database", "id": "ngs360"}}),
    )

    assert response.status_code == 422


def test_chat_rejects_more_references_than_the_cap(client, fake_langgraph):
    """Rejected, not truncated: silently dropping context is the bug being fixed."""
    response = client.post(
        "/api/v1/chat",
        json=_envelope(
            context={
                "references": [
                    {"type": "project", "id": f"P-{n:04d}"}
                    for n in range(MAX_CONTEXT_REFERENCES + 1)
                ]
            }
        ),
    )

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


# --- The agent deployment is unreachable ------------------------------------
#
# A 503 from the deployment must reach the caller as 502 (bad gateway: our
# upstream failed), never 500. The streaming route is the exception, and only
# once its SSE body has started.


def test_new_chat_502s_when_the_agent_is_unavailable(
    client, fake_langgraph, chat_user
):
    """Creating the thread for a brand-new chat degrades to 502, not 500.

    threads.create was the one upstream call in the module without a guard, so
    an outage escaped as an unhandled exception and Starlette returned a bare
    500 with a stack trace.
    """
    fake_langgraph(FakeLangGraphClient(thread_create_error=_unavailable()))

    response = client.post("/api/v1/chat", json=_envelope("hi"))

    assert response.status_code == 502


def test_new_chat_stream_502s_when_the_agent_is_unavailable(
    client, fake_langgraph, chat_user
):
    """The streaming route resolves its thread before the SSE body starts.

    So an outage there is still answerable with a status code, rather than the
    in-band error the generator has to fall back on later.
    """
    fake_langgraph(FakeLangGraphClient(thread_create_error=_unavailable()))

    response = client.post("/api/v1/chat/stream", json=_envelope("hi"))

    assert response.status_code == 502


def test_list_threads_502s_when_the_agent_is_unavailable(
    client, fake_langgraph, chat_user
):
    """History listing reports the upstream failure rather than an empty list."""
    fake_langgraph(FakeLangGraphClient(thread_search_error=_unavailable()))

    response = client.get("/api/v1/chat/threads")

    assert response.status_code == 502


def test_continuing_a_thread_502s_when_the_agent_is_unavailable(
    client, fake_langgraph, chat_user
):
    """The ownership lookup fails closed on an outage; it can't read as "absent"."""
    fake_langgraph(FakeLangGraphClient(thread_get_error=_unavailable()))

    response = client.post(
        "/api/v1/chat",
        json=_envelope("hi", thread_id="6d1f1e5c-6a5a-4c1e-9d3b-0f2a7b8c9d02"),
    )

    assert response.status_code == 502


# --- Chat is not configured at all ------------------------------------------
#
# LANGGRAPH_DEPLOYMENT_URL / LANGSMITH_API_KEY unset leaves the client None, so
# every route has to say so rather than raising an AttributeError.


@pytest.mark.parametrize(
    "method,path",
    [
        ("post", "/api/v1/chat"),
        ("get", "/api/v1/chat/threads"),
        ("delete", "/api/v1/chat/threads"),
        ("get", f"/api/v1/chat/threads/{uuid.uuid4()}"),
        ("get", f"/api/v1/chat/threads/{uuid.uuid4()}/messages"),
        ("delete", f"/api/v1/chat/threads/{uuid.uuid4()}"),
    ],
)
def test_routes_502_when_the_agent_is_not_configured(
    client, fake_langgraph, chat_user, method, path
):
    """Every non-streaming chat route reports an unconfigured agent as 502."""
    fake_langgraph(None)

    kwargs = {"json": _envelope("hi")} if method == "post" else {}
    response = getattr(client, method)(path, **kwargs)

    assert response.status_code == 502
    assert response.json()["detail"] == "Chat agent is not configured"


def test_chat_stream_reports_an_unconfigured_agent_in_band(
    client, fake_langgraph, chat_user
):
    """The streaming route answers 200 and puts the failure in the stream.

    useChat only understands the SSE protocol, so a protocol-shaped error is
    what surfaces in the UI. This is why get_langgraph_client yields None
    instead of raising, and why /chat/stream keeps the nullable dependency.
    """
    fake_langgraph(None)

    response = client.post("/api/v1/chat/stream", json=_envelope("hi"))

    assert response.status_code == 200
    chunks = _sse_data_chunks(response.text)
    # No thread frame: there is no thread, and nothing was invoked.
    assert chunks == [
        {"type": "error", "message": "Chat agent is not configured"}
    ]


# --- The frame models themselves ---------------------------------------------
#
# The tests above assert on the JSON that reaches the client, which is what the
# contract actually is. These assert on the models that produce it.
#
# Note what is NOT asserted here any more: the AI SDK's rules. Those are checked
# where the SDK actually is, in the client transport's mapping against the real
# types. These frames are ours, so all that is left to pin is our own shape.


def test_a_frame_serializes_to_exactly_the_expected_json():
    """The wire bytes, spelled out: snake_case, no SDK framing, nothing extra."""
    from api.chat.models import ChatFrameStatus, ChatFrameText, ChatFrameThread

    assert ChatFrameThread(thread_id="abc").model_dump_json() == (
        '{"type":"thread","thread_id":"abc"}'
    )
    assert ChatFrameStatus(tool="query_database").model_dump_json() == (
        '{"type":"status","tool":"query_database"}'
    )
    assert ChatFrameText(delta="hi").model_dump_json() == (
        '{"type":"text","delta":"hi"}'
    )


def test_the_frame_union_covers_exactly_the_types_the_stream_emits():
    """The contract is closed: five frames, and none of them SDK frames.

    Pinned so adding one is a deliberate change here, paired with teaching the
    client transport to map it — a frame the transport does not know is a frame
    the browser silently drops.
    """
    import typing

    from api.chat.models import ChatFrame

    members = typing.get_args(typing.get_args(ChatFrame)[0])
    emitted = {
        typing.get_args(m.model_fields["type"].annotation)[0] for m in members
    }
    assert emitted == {"thread", "status", "text", "done", "error"}


def test_no_frame_of_a_whole_run_serializes_a_null(client, fake_langgraph):
    """No frame carries a null: every field is required and always filled.

    Kept because it is cheap and because a null on the wire is a bug in any
    protocol, not only the SDK's.
    """
    fake_langgraph(
        FakeLangGraphClient(
            script=[
                _tool_call_event("query_database", {"sql": "SELECT 1"}),
                _tool_result_event("11013", name="query_database"),
                _message_event("There are 11013."),
            ]
        )
    )

    chunks = _stream_chunks(client, text="how many?")

    assert {c["type"] for c in chunks} == {"thread", "status", "text", "done"}
    for chunk in chunks:
        assert None not in _nested_values(chunk), chunk


def _nested_values(value):
    """Every scalar reachable inside a parsed frame, for the no-null assertion."""
    if isinstance(value, dict):
        return [v for item in value.values() for v in _nested_values(item)]
    if isinstance(value, list):
        return [v for item in value for v in _nested_values(item)]
    return [value]
