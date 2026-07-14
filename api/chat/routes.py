"""
Routes/endpoints for the AI Assistant Chat API
"""

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse

from api.auth.deps import CurrentUser
from api.chat import services
from api.chat.models import ChatRequest

router = APIRouter(prefix="/chat", tags=["Chat Endpoints"])


@router.post("")
async def chat(
    req: ChatRequest, current_user: CurrentUser, request: Request
) -> JSONResponse:
    """Non-streaming JSON chat for simple clients and tests."""
    result = await services.run_chat(req, request.app.state.langgraph)
    return JSONResponse(result)


@router.post("/stream")
async def chat_stream(
    req: ChatRequest, current_user: CurrentUser, request: Request
) -> StreamingResponse:
    """Streaming chat for the chat UI (Vercel AI SDK UI Message Stream protocol)."""
    return StreamingResponse(
        services.stream_chat_vercel(req, request.app.state.langgraph),
        media_type="text/event-stream",
        headers={
            "x-vercel-ai-ui-message-stream": "v1",  # required by the AI SDK protocol
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",  # prevent proxy buffering of the stream
        },
    )


@router.get("/threads/{thread_id}")
async def get_thread(thread_id: str, current_user: CurrentUser, request: Request):
    """Fetch a LangGraph thread's state for transcript reload / reconnect."""
    client = request.app.state.langgraph
    if client is None:
        raise HTTPException(status_code=502, detail="Chat agent is not configured")
    try:
        return await client.threads.get_state(thread_id)
    except Exception as exc:
        raise HTTPException(
            status_code=404, detail=f"Thread lookup failed: {type(exc).__name__}"
        ) from exc
