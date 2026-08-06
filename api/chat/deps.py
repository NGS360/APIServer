"""
Chat dependencies for dependency injection
"""

from typing import Annotated, Any

from fastapi import Depends, HTTPException

from api.auth.deps import CurrentUser, oauth2_scheme_optional
from api.chat import services
from core.deps import LangGraphDep

# The caller's raw bearer credential, forwarded to the agent so its NGS360 API
# tools act as this user rather than as a service account. CurrentUser resolves
# the same credential to a User and discards the string, so this asks for it
# separately.
#
# Whatever the client sent is passed through verbatim — a JWT or an ngs360_ API
# key — because the NGS360 API accepts both and the agent only needs to replay
# it. Nothing here re-validates it: CurrentUser on the same route has already
# rejected the request if it is not good.
#
# The *optional* extractor on purpose. Enforcing the credential is CurrentUser's
# job on the same route; the strict scheme would only duplicate that 401, while
# making every route that overrides get_current_user (i.e. the tests) fail for a
# reason unrelated to what they check. None here therefore never means
# "unauthenticated" — it means the credential was supplied some other way, and
# the agent falls back to its read-only posture rather than acting as a user it
# cannot name.
RawUserToken = Annotated[str | None, Depends(oauth2_scheme_optional)]


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
