"""Tests for the AI Assistant chat streaming endpoint."""

import json


def _post_chat(client, text="What is NGS360?"):
    return client.post(
        "/api/v1/chat",
        json={
            "messages": [
                {
                    "id": "u1",
                    "role": "user",
                    "parts": [{"type": "text", "text": text}],
                }
            ]
        },
    )


def test_chat_streams_ui_message_protocol(client):
    """The endpoint must emit a valid UI Message Stream over SSE."""
    response = _post_chat(client)

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


def test_chat_requires_auth(unauthenticated_client):
    response = _post_chat(unauthenticated_client)
    assert response.status_code == 401


def test_chat_handles_empty_history(client):
    response = client.post("/api/v1/chat", json={"messages": []})
    assert response.status_code == 200
    assert "data: [DONE]" in response.text
