"""
Routes/endpoints for the AI Assistant Chat API
"""

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse, StreamingResponse

from api.auth.deps import CurrentUser
from api.chat import services
from api.chat.models import ChatRequest
from core.deps import LangGraphDep

router = APIRouter(prefix="/chat", tags=["Chat Endpoints"])


@router.post("")
async def chat(
    req: ChatRequest, current_user: CurrentUser, client: LangGraphDep
) -> JSONResponse:
    """Non-streaming JSON chat for simple clients and tests."""
    result = await services.run_chat(req, client)
    return JSONResponse(result)


@router.post("/stream")
async def chat_stream(
    req: ChatRequest, current_user: CurrentUser, client: LangGraphDep
) -> StreamingResponse:
    """Streaming chat for the chat UI (Vercel AI SDK UI Message Stream protocol)."""
    return StreamingResponse(
        services.stream_chat_vercel(req, client),
        media_type="text/event-stream",
        headers={
            "x-vercel-ai-ui-message-stream": "v1",  # required by the AI SDK protocol
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",  # prevent proxy buffering of the stream
        },
    )


@router.get("/threads/{thread_id}")
async def get_thread(thread_id: str, current_user: CurrentUser, client: LangGraphDep):
    """Fetch a LangGraph thread's state for transcript reload / reconnect."""
    if client is None:
        raise HTTPException(status_code=502, detail="Chat agent is not configured")
    try:
        return await client.threads.get_state(thread_id)
    except Exception as exc:
        raise HTTPException(
            status_code=404, detail=f"Thread lookup failed: {type(exc).__name__}"
        ) from exc
