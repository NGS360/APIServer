"""
Unit tests for the chat API routes and models.

Tests cover:
- POST /api/v1/chat with valid message (200 + conversation_id)
- Unauthenticated request (401)
- stream=false returns JSON ChatResponse
- stream=true returns SSE text/event-stream
- Missing conversation_id creates new conversation
- Agent error returns 500
- Bedrock service error returns 503
- Timeout returns 504
- Memory failure returns 200 with warning

Requirements: 4.1–4.7, 6.3, 8.1, 8.3, 8.4
"""

import asyncio
import json
import uuid
from collections.abc import AsyncGenerator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from api.chat.models import ChatRequest, ChatResponse, ChatStreamEvent


# ---------------------------------------------------------------------------
# Model validation tests
# ---------------------------------------------------------------------------

class TestChatModels:
    """Unit tests for Pydantic request/response models."""

    def test_chat_request_defaults(self):
        req = ChatRequest(message="hello")
        assert req.message == "hello"
        assert req.conversation_id is None
        assert req.stream is True

    def test_chat_request_explicit_fields(self):
        req = ChatRequest(
            message="hi", conversation_id="conv-1", stream=False
        )
        assert req.conversation_id == "conv-1"
        assert req.stream is False

    def test_chat_request_rejects_extra_fields(self):
        with pytest.raises(Exception):
            ChatRequest(message="hi", unknown_field="bad")

    def test_chat_response_fields(self):
        resp = ChatResponse(response="answer", conversation_id="c-1")
        assert resp.response == "answer"
        assert resp.conversation_id == "c-1"

    def test_chat_stream_event_text(self):
        evt = ChatStreamEvent(event="text", data="chunk", conversation_id="c-1")
        assert evt.event == "text"

    def test_chat_stream_event_error(self):
        evt = ChatStreamEvent(event="error", data="oops")
        assert evt.conversation_id is None

    def test_chat_stream_event_done(self):
        evt = ChatStreamEvent(event="done", data="")
        assert evt.event == "done"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

CHAT_URL = "/api/v1/chat"
FAKE_CONV_ID = str(uuid.uuid4())


def _mock_sync_response(conv_id: str | None = None):
    """Return a ChatResponse as process_message would for stream=False."""
    cid = conv_id or FAKE_CONV_ID
    return ChatResponse(response="Hello from agent", conversation_id=cid)


def _make_stream_generator(conv_id: str | None = None):
    """Return an async generator as process_message would for stream=True."""
    cid = conv_id or FAKE_CONV_ID

    async def gen() -> AsyncGenerator[str, None]:
        evt = ChatStreamEvent(event="text", data="Hello", conversation_id=cid)
        yield f"event: text\ndata: {evt.model_dump_json()}\n\n"
        done = ChatStreamEvent(event="done", data="", conversation_id=cid)
        yield f"event: done\ndata: {done.model_dump_json()}\n\n"

    return gen()


def _make_stream_with_warning(conv_id: str | None = None):
    """Stream response that includes a memory warning as first event."""
    cid = conv_id or FAKE_CONV_ID

    async def gen() -> AsyncGenerator[str, None]:
        warn = ChatStreamEvent(
            event="text",
            data="⚠️ Conversation history could not be loaded. "
                 "Responding without prior context.\n\n",
            conversation_id=cid,
        )
        yield f"event: text\ndata: {warn.model_dump_json()}\n\n"
        evt = ChatStreamEvent(event="text", data="Answer", conversation_id=cid)
        yield f"event: text\ndata: {evt.model_dump_json()}\n\n"
        done = ChatStreamEvent(event="done", data="", conversation_id=cid)
        yield f"event: done\ndata: {done.model_dump_json()}\n\n"

    return gen()



# ---------------------------------------------------------------------------
# Route tests — stream=False (JSON responses)
# ---------------------------------------------------------------------------

class TestChatEndpointSync:
    """Tests for POST /api/v1/chat with stream=false (JSON mode)."""

    @patch("api.chat.routes.process_message", new_callable=AsyncMock)
    def test_valid_message_returns_200_with_conversation_id(
        self, mock_pm, client: TestClient, auth_headers
    ):
        """Req 4.1, 4.3: valid message → 200 + conversation_id."""
        mock_pm.return_value = _mock_sync_response()

        resp = client.post(
            CHAT_URL,
            json={"message": "List projects", "stream": False},
            headers=auth_headers,
        )
        assert resp.status_code == 200
        body = resp.json()
        assert "response" in body
        assert "conversation_id" in body
        assert body["conversation_id"] == FAKE_CONV_ID

    @patch("api.chat.routes.process_message", new_callable=AsyncMock)
    def test_stream_false_returns_json(
        self, mock_pm, client: TestClient, auth_headers
    ):
        """Req 4.7: stream=false → JSON ChatResponse."""
        mock_pm.return_value = _mock_sync_response()

        resp = client.post(
            CHAT_URL,
            json={"message": "hi", "stream": False},
            headers=auth_headers,
        )
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("application/json")
        body = resp.json()
        assert body["response"] == "Hello from agent"

    @patch("api.chat.routes.process_message", new_callable=AsyncMock)
    def test_missing_conversation_id_creates_new(
        self, mock_pm, client: TestClient, auth_headers
    ):
        """Req 4.5: no conversation_id → response has a new one."""
        new_id = str(uuid.uuid4())
        mock_pm.return_value = ChatResponse(
            response="ok", conversation_id=new_id
        )

        resp = client.post(
            CHAT_URL,
            json={"message": "hello", "stream": False},
            headers=auth_headers,
        )
        assert resp.status_code == 200
        assert resp.json()["conversation_id"] == new_id

    @patch("api.chat.routes.process_message", new_callable=AsyncMock)
    def test_conversation_id_forwarded(
        self, mock_pm, client: TestClient, auth_headers
    ):
        """Req 4.3: existing conversation_id is forwarded to service."""
        existing_id = "conv-existing-123"
        mock_pm.return_value = ChatResponse(
            response="ok", conversation_id=existing_id
        )

        resp = client.post(
            CHAT_URL,
            json={
                "message": "follow-up",
                "conversation_id": existing_id,
                "stream": False,
            },
            headers=auth_headers,
        )
        assert resp.status_code == 200
        # Verify process_message was called with the conversation_id
        call_kwargs = mock_pm.call_args.kwargs
        assert call_kwargs["conversation_id"] == existing_id


# ---------------------------------------------------------------------------
# Route tests — stream=True (SSE responses)
# ---------------------------------------------------------------------------

class TestChatEndpointStream:
    """Tests for POST /api/v1/chat with stream=true (SSE mode)."""

    @patch("api.chat.routes.process_message", new_callable=AsyncMock)
    def test_stream_true_returns_sse_content_type(
        self, mock_pm, client: TestClient, auth_headers
    ):
        """Req 4.4, 4.7: stream=true → text/event-stream."""
        mock_pm.return_value = _make_stream_generator()

        resp = client.post(
            CHAT_URL,
            json={"message": "hi", "stream": True},
            headers=auth_headers,
        )
        assert resp.status_code == 200
        assert "text/event-stream" in resp.headers["content-type"]

    @patch("api.chat.routes.process_message", new_callable=AsyncMock)
    def test_stream_contains_text_and_done_events(
        self, mock_pm, client: TestClient, auth_headers
    ):
        """SSE stream includes text events followed by a done event."""
        mock_pm.return_value = _make_stream_generator()

        resp = client.post(
            CHAT_URL,
            json={"message": "hi", "stream": True},
            headers=auth_headers,
        )
        body = resp.text
        assert "event: text" in body
        assert "event: done" in body

    @patch("api.chat.routes.process_message", new_callable=AsyncMock)
    def test_stream_default_when_omitted(
        self, mock_pm, client: TestClient, auth_headers
    ):
        """stream defaults to True when not provided."""
        mock_pm.return_value = _make_stream_generator()

        resp = client.post(
            CHAT_URL,
            json={"message": "hi"},
            headers=auth_headers,
        )
        assert "text/event-stream" in resp.headers["content-type"]


# ---------------------------------------------------------------------------
# Authentication tests
# ---------------------------------------------------------------------------

class TestChatAuth:
    """Tests for authentication on the chat endpoint."""

    def test_unauthenticated_returns_401(
        self, unauthenticated_client: TestClient
    ):
        """Req 4.2, 6.3: missing JWT → 401."""
        resp = unauthenticated_client.post(
            CHAT_URL,
            json={"message": "hi", "stream": False},
        )
        assert resp.status_code == 401

    def test_invalid_token_returns_401(
        self, unauthenticated_client: TestClient
    ):
        """Req 6.3: invalid JWT → 401."""
        resp = unauthenticated_client.post(
            CHAT_URL,
            json={"message": "hi", "stream": False},
            headers={"Authorization": "Bearer invalid-token-xyz"},
        )
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Error handling tests — sync mode
# ---------------------------------------------------------------------------

class TestChatErrorHandlingSync:
    """Error handling tests using stream=false for simpler assertions."""

    @patch("api.chat.routes.process_message", new_callable=AsyncMock)
    def test_agent_error_returns_500(
        self, mock_pm, client: TestClient, auth_headers
    ):
        """Req 4.6: unhandled agent exception → 500."""
        from fastapi import HTTPException

        mock_pm.side_effect = HTTPException(
            status_code=500,
            detail="An error occurred while processing your message.",
        )

        resp = client.post(
            CHAT_URL,
            json={"message": "hi", "stream": False},
            headers=auth_headers,
        )
        assert resp.status_code == 500
        assert "error" in resp.json()["detail"].lower() or "occurred" in resp.json()["detail"].lower()

    @patch("api.chat.routes.process_message", new_callable=AsyncMock)
    def test_bedrock_error_returns_503(
        self, mock_pm, client: TestClient, auth_headers
    ):
        """Req 8.1: Bedrock service error → 503."""
        from fastapi import HTTPException

        mock_pm.side_effect = HTTPException(
            status_code=503,
            detail="AI service is temporarily unavailable.",
        )

        resp = client.post(
            CHAT_URL,
            json={"message": "hi", "stream": False},
            headers=auth_headers,
        )
        assert resp.status_code == 503
        assert "temporarily unavailable" in resp.json()["detail"]

    @patch("api.chat.routes.process_message", new_callable=AsyncMock)
    def test_timeout_returns_504(
        self, mock_pm, client: TestClient, auth_headers
    ):
        """Req 8.4: timeout → 504."""
        from fastapi import HTTPException

        mock_pm.side_effect = HTTPException(
            status_code=504,
            detail="Request timed out.",
        )

        resp = client.post(
            CHAT_URL,
            json={"message": "hi", "stream": False},
            headers=auth_headers,
        )
        assert resp.status_code == 504
        assert "timed out" in resp.json()["detail"].lower()

    @patch("api.chat.routes.process_message", new_callable=AsyncMock)
    def test_memory_failure_returns_200_with_warning(
        self, mock_pm, client: TestClient, auth_headers
    ):
        """Req 8.3: memory failure → 200 with warning text."""
        warning_text = "⚠️ Conversation history could not be loaded."
        mock_pm.return_value = ChatResponse(
            response=f"{warning_text}\n\nHere is your answer.",
            conversation_id=FAKE_CONV_ID,
        )

        resp = client.post(
            CHAT_URL,
            json={"message": "hi", "stream": False},
            headers=auth_headers,
        )
        assert resp.status_code == 200
        assert "could not be loaded" in resp.json()["response"]


# ---------------------------------------------------------------------------
# Error handling tests — streaming mode
# ---------------------------------------------------------------------------

class TestChatErrorHandlingStream:
    """Error handling in SSE streaming mode."""

    @patch("api.chat.routes.process_message", new_callable=AsyncMock)
    def test_stream_memory_warning_included(
        self, mock_pm, client: TestClient, auth_headers
    ):
        """Req 8.3: memory warning appears as first SSE event in stream."""
        mock_pm.return_value = _make_stream_with_warning()

        resp = client.post(
            CHAT_URL,
            json={"message": "hi", "stream": True},
            headers=auth_headers,
        )
        assert resp.status_code == 200
        assert "could not be loaded" in resp.text


# ---------------------------------------------------------------------------
# Service-level tests (process_message)
# ---------------------------------------------------------------------------

class TestProcessMessage:
    """Tests for the process_message service function directly."""

    @patch("api.chat.services.create_agent")
    def test_sync_returns_chat_response(self, mock_create):
        """process_message with stream=False returns ChatResponse."""
        conv_id = str(uuid.uuid4())
        mock_agent = MagicMock()
        mock_agent.invoke_async = AsyncMock(return_value="Agent says hi")
        mock_create.return_value = (mock_agent, conv_id, None)

        from api.chat.services import process_message

        result = asyncio.get_event_loop().run_until_complete(
            process_message(
                user_jwt="fake-jwt",
                user_id="user-1",
                message="hello",
                conversation_id=None,
                stream=False,
            )
        )
        assert isinstance(result, ChatResponse)
        assert result.conversation_id == conv_id
        assert "Agent says hi" in result.response

    @patch("api.chat.services.create_agent")
    def test_sync_timeout_raises_504(self, mock_create):
        """process_message raises 504 on timeout."""
        conv_id = str(uuid.uuid4())

        async def slow_invoke(msg):
            await asyncio.sleep(999)

        mock_agent = MagicMock()
        mock_agent.invoke_async = slow_invoke
        mock_create.return_value = (mock_agent, conv_id, None)

        # Patch CHAT_TIMEOUT_SECONDS to a tiny value
        with patch("api.chat.services.get_settings") as mock_settings:
            settings = MagicMock()
            settings.CHAT_TIMEOUT_SECONDS = 0.01
            settings.BEDROCK_MODEL_ID = "test"
            settings.BEDROCK_REGION = "us-east-1"
            settings.AGENTCORE_MEMORY_ID = None
            settings.CHAT_API_BASE_URL = "http://fake"
            mock_settings.return_value = settings

            from api.chat.services import process_message
            from fastapi import HTTPException

            with pytest.raises(HTTPException) as exc_info:
                asyncio.get_event_loop().run_until_complete(
                    process_message(
                        user_jwt="jwt",
                        user_id="u1",
                        message="hi",
                        stream=False,
                    )
                )
            assert exc_info.value.status_code == 504

    @patch("api.chat.services.create_agent")
    def test_sync_bedrock_error_raises_503(self, mock_create):
        """process_message raises 503 on Bedrock errors."""
        from botocore.exceptions import EndpointConnectionError

        conv_id = str(uuid.uuid4())

        async def bedrock_fail(msg):
            raise EndpointConnectionError(endpoint_url="https://bedrock.us-east-1")

        mock_agent = MagicMock()
        mock_agent.invoke_async = bedrock_fail
        mock_create.return_value = (mock_agent, conv_id, None)

        from api.chat.services import process_message
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc_info:
            asyncio.get_event_loop().run_until_complete(
                process_message(
                    user_jwt="jwt",
                    user_id="u1",
                    message="hi",
                    stream=False,
                )
            )
        assert exc_info.value.status_code == 503

    @patch("api.chat.services.create_agent")
    def test_sync_generic_error_raises_500(self, mock_create):
        """process_message raises 500 on generic agent errors."""
        conv_id = str(uuid.uuid4())

        async def agent_fail(msg):
            raise RuntimeError("something broke")

        mock_agent = MagicMock()
        mock_agent.invoke_async = agent_fail
        mock_create.return_value = (mock_agent, conv_id, None)

        from api.chat.services import process_message
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc_info:
            asyncio.get_event_loop().run_until_complete(
                process_message(
                    user_jwt="jwt",
                    user_id="u1",
                    message="hi",
                    stream=False,
                )
            )
        assert exc_info.value.status_code == 500

    @patch("api.chat.services.create_agent")
    def test_sync_memory_warning_included_in_response(self, mock_create):
        """process_message includes memory warning in response text."""
        conv_id = str(uuid.uuid4())
        mock_agent = MagicMock()
        mock_agent.invoke_async = AsyncMock(return_value="Answer")
        mock_create.return_value = (
            mock_agent,
            conv_id,
            "Conversation history could not be loaded.",
        )

        from api.chat.services import process_message

        result = asyncio.get_event_loop().run_until_complete(
            process_message(
                user_jwt="jwt",
                user_id="u1",
                message="hi",
                stream=False,
            )
        )
        assert isinstance(result, ChatResponse)
        assert "could not be loaded" in result.response
        assert "Answer" in result.response

    @patch("api.chat.services.create_agent")
    def test_create_agent_bedrock_error_raises_503(self, mock_create):
        """If create_agent itself fails with a Bedrock error → 503."""
        from botocore.exceptions import EndpointConnectionError

        mock_create.side_effect = EndpointConnectionError(
            endpoint_url="https://bedrock.us-east-1"
        )

        from api.chat.services import process_message
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc_info:
            asyncio.get_event_loop().run_until_complete(
                process_message(
                    user_jwt="jwt",
                    user_id="u1",
                    message="hi",
                    stream=False,
                )
            )
        assert exc_info.value.status_code == 503


# ---------------------------------------------------------------------------
# Validation tests
# ---------------------------------------------------------------------------

class TestChatValidation:
    """Request validation edge cases."""

    def test_empty_body_returns_422(
        self, client: TestClient, auth_headers
    ):
        """Missing body → 422."""
        resp = client.post(CHAT_URL, headers=auth_headers)
        assert resp.status_code == 422

    def test_missing_message_returns_422(
        self, client: TestClient, auth_headers
    ):
        """Body without message field → 422."""
        resp = client.post(
            CHAT_URL,
            json={"stream": False},
            headers=auth_headers,
        )
        assert resp.status_code == 422

    @patch("api.chat.routes.process_message", new_callable=AsyncMock)
    def test_extra_fields_rejected(
        self, mock_pm, client: TestClient, auth_headers
    ):
        """ChatRequest(extra='forbid') rejects unknown fields."""
        resp = client.post(
            CHAT_URL,
            json={"message": "hi", "stream": False, "rogue": "field"},
            headers=auth_headers,
        )
        assert resp.status_code == 422
