"""
Chat API routes.

Provides the POST /chat endpoint for the NGS360 AI Chatbot.
Supports both SSE streaming and synchronous JSON responses.
"""

import logging

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import JSONResponse, StreamingResponse

from api.auth.deps import CurrentUser, oauth2_scheme
from api.chat.models import ChatRequest, ChatResponse
from api.chat.services import process_message

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/chat", tags=["Chat Endpoints"])


@router.post("", response_model=None)
async def chat(
    request: ChatRequest,
    current_user: CurrentUser,
    token: str = Depends(oauth2_scheme),
) -> StreamingResponse | ChatResponse | JSONResponse:
    """
    Send a message to the AI chatbot.

    Streams SSE by default, or returns JSON if stream=false.
    The user's JWT is forwarded to the agent so all NGS360 API
    calls respect the user's existing permissions.
    """
    try:
        result = await process_message(
            user_jwt=token,
            user_id=str(current_user.id),
            message=request.message,
            conversation_id=request.conversation_id,
            stream=request.stream,
        )

        if request.stream:
            return StreamingResponse(
                result,
                media_type="text/event-stream",
            )

        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Unhandled error in chat endpoint: %s", e)
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={"detail": "An error occurred while processing your message."},
        )
