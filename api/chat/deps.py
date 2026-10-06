"""
Chat dependencies for dependency injection
"""

from typing import Annotated, Any

from fastapi import Depends, HTTPException

from api.auth.deps import CurrentUser
from api.chat import services
from core.deps import LangGraphDep


def get_chat_client(client: LangGraphDep) -> Any:
    """The LangGraph client, or 502 when chat is unconfigured.

    Strict sibling of LangGraphDep, which yields None on purpose: the streaming
    route can't answer with a status once the SSE body has started, so it keeps
    the nullable dependency and reports the failure in-band instead.
    """
    if client is None:
        raise HTTPException(
            status_code=502, detail="Chat agent is not configured"
        )
    return client


ChatClientDep = Annotated[Any, Depends(get_chat_client)]


async def get_owned_thread(
    thread_id: str, current_user: CurrentUser, client: ChatClientDep
) -> dict[str, Any]:
    """The path's thread, or 404 if it is absent or someone else's.

    Declaring this on a route is what enforces ownership, so any new route
    taking a thread_id path parameter has to ask for it.
    """
    return await services.require_owned_thread(
        client, thread_id, str(current_user.id)
    )


OwnedThreadDep = Annotated[dict[str, Any], Depends(get_owned_thread)]
