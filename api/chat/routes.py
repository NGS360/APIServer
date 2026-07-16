"""
Routes/endpoints for the AI Assistant Chat API
"""

from fastapi import APIRouter, WebSocket, HTTPException, WebSocketDisconnect
from fastapi.responses import JSONResponse, StreamingResponse
import json
import asyncio

from api.auth.deps import CurrentUser
from core.deps import LangGraphDep
from api.chat import services
from api.chat.models import ChatRequest

router = APIRouter(prefix="/chat", tags=["Chat Endpoints"])


# @router.post("")
# async def chat(request: ChatRequest, current_user: CurrentUser) -> StreamingResponse:
#     """Stream an assistant reply for the given message history."""
#     return StreamingResponse(
#         services.stream_reply(request.messages, current_user.username, request.context),
#         media_type="text/event-stream",
#         headers={
#             "x-vercel-ai-ui-message-stream": "v1",  # required by the AI SDK protocol
#             "Cache-Control": "no-cache",
#             "X-Accel-Buffering": "no",  # prevent proxy buffering of the stream
#         },
#     )

@router.post("")
async def chat(req: ChatRequest, current_user: CurrentUser, langgraph_client: LangGraphDep) -> JSONResponse:
    """A JSON route for non-streaming chat for simple clients or tests """
    result = await services.run_chat(req, langgraph_client)
    return JSONResponse(result)


@router.post("/stream")
async def chat_stream(req: ChatRequest, current_user: CurrentUser, langgraph_client: LangGraphDep) -> StreamingResponse:
    """A streaming route for the chat UI"""
    LANGSMITH_ASSISTANT_ID = 'agent'

    async def event_source():
        thread_id = req.thread_id
        if not thread_id:
            thread = await langgraph_client.threads.create()
            thread_id = thread["thread_id"]

        yield f"event: meta\ndata: {json.dumps({'thread_id': thread_id})}\n\n"

        try:
            async with asyncio.timeout(120):
                async for chunk in langgraph_client.runs.stream(
                    thread_id,
                    LANGSMITH_ASSISTANT_ID,
                    input={"messages": [{"role": "user", "content": req.message}]},
                    stream_mode="messages-tuple",
                ):
                    if chunk.event != "messages":
                        continue
                    message_chunk, metadata = chunk.data
                    token = message_chunk.get("content")
                    if token:
                        payload = {"token": token, "metadata": metadata}
                        yield f"event: token\ndata: {json.dumps(payload)}\n\n"

            yield "event: done\ndata: {}\n\n"

        except TimeoutError:
            yield "event: error\ndata: {\"code\":\"upstream_timeout\"}\n\n"
        except Exception as exc:
            safe_detail = str(exc).replace("\n", " ")[:300]
            yield f"event: error\ndata: {json.dumps({'code': 'upstream_error', 'detail': safe_detail})}\n\n"

    return StreamingResponse(
        event_source(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        },
    )


@router.get(
    "/threads/{thread_id}",
    responses={404: {"description": "Thread lookup failed"}}
)
async def get_thread(thread_id: str, current_user: CurrentUser, langgraph_client: LangGraphDep):
    try:
        state = await langgraph_client.state.langgraph.threads.get_state(thread_id)
        return state
    except Exception as exc:
        raise HTTPException(
            status_code=404,
            detail=f"Thread lookup failed: {type(exc).__name__}"
        ) from exc


@router.websocket("/ws")
async def chat_ws(websocket: WebSocket, current_user: CurrentUser, langgraph_client: LangGraphDep):
    """A thread-state route for transcript reload, reconnect, and polling fallback."""
    await websocket.accept()
    LANGSMITH_ASSISTANT_ID = 'agent'
    try:
        payload = await websocket.receive_json()
        req = ChatRequest(**payload)

        thread_id = req.thread_id
        if not thread_id:
            thread = await langgraph_client.threads.create()
            thread_id = thread["thread_id"]

        await websocket.send_json({"type": "meta", "thread_id": thread_id})

        async with asyncio.timeout(120):
            async for chunk in langgraph_client.runs.stream(
                thread_id,
                LANGSMITH_ASSISTANT_ID,
                input={"messages": [{"role": "user", "content": req.message}]},
                stream_mode="messages-tuple",
            ):
                if chunk.event != "messages":
                    continue
                message_chunk, metadata = chunk.data
                token = message_chunk.get("content")
                if token:
                    await websocket.send_json(
                        {"type": "token", "token": token, "metadata": metadata}
                    )

        await websocket.send_json({"type": "done"})

    except WebSocketDisconnect:
        return
    except Exception as exc:
        await websocket.send_json(
            {"type": "error", "detail": str(exc).replace("\n", " ")[:300]}
        )
        await websocket.close(code=1011)
