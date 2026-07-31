"""
Routes/endpoints for the AI Assistant Chat API
"""

from fastapi import APIRouter, HTTPException, Query, Response
from fastapi.responses import JSONResponse, StreamingResponse

from api.auth.deps import CurrentUser
from api.chat import services
from api.chat.deps import ChatClientDep, OwnedThreadDep
from api.chat.models import ChatRequest, ChatThreadMessages, ChatThreadsPublic
from core.deps import LangGraphDep

router = APIRouter(prefix="/chat", tags=["Chat Endpoints"])


@router.post("")
async def chat(
    req: ChatRequest, current_user: CurrentUser, client: ChatClientDep
) -> JSONResponse:
    """Non-streaming JSON chat for simple clients and tests."""
    result = await services.run_chat(req, client, str(current_user.id))
    return JSONResponse(result)


@router.post("/stream")
async def chat_stream(
    req: ChatRequest, current_user: CurrentUser, client: LangGraphDep
) -> StreamingResponse:
    """Streaming chat for the chat UI (Vercel AI SDK UI Message Stream protocol)."""
    # Resolve the thread up front: once the SSE body starts, a failure can only
    # be an in-band error chunk on a 200, so the ownership check has to happen
    # while a 404 is still possible.
    thread_id = (
        None
        if client is None
        else await services.resolve_thread(req, client, str(current_user.id))
    )
    return StreamingResponse(
        services.stream_chat_vercel(req, client, thread_id),
        media_type="text/event-stream",
        headers={
            "x-vercel-ai-ui-message-stream": "v1",  # required by the AI SDK protocol
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",  # prevent proxy buffering of the stream
        },
    )


@router.get("/threads")
async def list_chat_threads(
    current_user: CurrentUser,
    client: ChatClientDep,
    skip: int = Query(0, ge=0, description="Number of threads to skip"),
    limit: int = Query(
        20, ge=1, le=100, description="Maximum number of threads to return"
    ),
) -> ChatThreadsPublic:
    """List the caller's chat threads, most recently active first."""
    result = await services.list_threads(
        client, str(current_user.id), skip=skip, limit=limit
    )
    return ChatThreadsPublic(**result)


@router.delete("/threads", status_code=204)
async def delete_all_chat_threads(
    current_user: CurrentUser, client: ChatClientDep
) -> Response:
    """Delete all of the caller's chat threads."""
    await services.delete_all_threads(client, str(current_user.id))
    return Response(status_code=204)


@router.get("/threads/{thread_id}/messages")
async def get_chat_thread_messages(
    thread_id: str, thread: OwnedThreadDep, client: ChatClientDep
) -> ChatThreadMessages:
    """A thread's transcript as the user saw it, for reloading it into the chat.

    The thread itself carries the agent's full working state; this is the subset
    that was on screen. See GET /chat/threads/{thread_id} for everything.
    """
    result = await services.get_thread_messages(client, thread_id)
    return ChatThreadMessages(**result)


@router.delete("/threads/{thread_id}", status_code=204)
async def delete_chat_thread(
    thread_id: str, thread: OwnedThreadDep, client: ChatClientDep
) -> Response:
    """Delete one thread, including the agent's memory of it."""
    await services.delete_thread(client, thread_id)
    return Response(status_code=204)


@router.get("/threads/{thread_id}")
async def get_thread(
    thread_id: str, thread: OwnedThreadDep, client: ChatClientDep
):
    """Fetch a thread's full checkpointed state, tool calls and executed SQL included.

    Raw state includes tool output and executed SQL, i.e. more than the owner ever
    saw in the UI — OwnedThreadDep is what keeps it from being served to anyone else.
    """
    try:
        return await client.threads.get_state(thread_id)
    except Exception as exc:
        raise HTTPException(
            status_code=404, detail=f"Thread lookup failed: {type(exc).__name__}"
        ) from exc
