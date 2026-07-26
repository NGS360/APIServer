"""
LangGraph configuration
"""

from core.config import get_settings
from core.logger import logger

client = None


def get_langgraph_client():
    global client

    if client:
        return client

    settings = get_settings()

    # Chat endpoints stay disabled (client is None) until both the deployment
    # URL and API key are configured (via env or Secrets Manager).
    if not settings.LANGGRAPH_DEPLOYMENT_URL or not settings.LANGSMITH_API_KEY:
        logger.warning(
            "LANGGRAPH_DEPLOYMENT_URL and/or LANGSMITH_API_KEY are not set - "
            "chat endpoints are disabled until they are configured (via env or "
            "Secrets Manager)."
        )
        client = None
        return client

    try:
        from langgraph_sdk import get_client as _get_langgraph_client

        client = _get_langgraph_client(
            url=settings.LANGGRAPH_DEPLOYMENT_URL,
            api_key=settings.LANGSMITH_API_KEY,
        )
        logger.info(
            "LangGraph chat client initialized (url=%s, assistant=%s)",
            settings.LANGGRAPH_DEPLOYMENT_URL,
            settings.LANGSMITH_ASSISTANT_ID,
        )
    except Exception as e:  # noqa: BLE001 - don't block startup on chat setup
        client = None
        logger.warning(f"Failed to initialize LangGraph chat client: {e}")

    return client
