from langgraph_sdk import get_client
from core.config import get_settings

langgraph_client = None


def get_langgraph_client():
    global langgraph_client

    if langgraph_client:
        return langgraph_client

    LANGSMITH_DEPLOYMENT_URL = get_settings().LANGSMITH_DEPLOYMENT_URL
    LANGSMITH_API_KEY = get_settings().LANGSMITH_API_KEY

    # LANGSMITH_ASSISTANT_ID = os.getenv("LANGSMITH_ASSISTANT_ID", "agent")

    if LANGSMITH_DEPLOYMENT_URL and LANGSMITH_API_KEY:
        langgraph_client = get_client(
            url=LANGSMITH_DEPLOYMENT_URL,
            api_key=LANGSMITH_API_KEY,
        )
        return langgraph_client
    return None
