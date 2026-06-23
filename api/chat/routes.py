"""
Routes/endpoints for the AI Assistant Chat API
"""

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from api.auth.deps import CurrentUser
from api.chat import services
from api.chat.models import ChatRequest

router = APIRouter(prefix="/chat", tags=["Chat Endpoints"])


@router.post("")
async def chat(request: ChatRequest, current_user: CurrentUser) -> StreamingResponse:
    """Stream an assistant reply for the given message history."""
    return StreamingResponse(
        services.stream_reply(request.messages, current_user.username, request.context),
        media_type="text/event-stream",
        headers={
            "x-vercel-ai-ui-message-stream": "v1",  # required by the AI SDK protocol
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",  # prevent proxy buffering of the stream
        },
    )
