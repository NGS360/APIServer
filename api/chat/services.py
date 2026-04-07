"""
Agent service for the NGS360 AI Chatbot.

Orchestrates Strands Agent creation with MCP tools, AgentCore Memory
for conversation persistence, and message processing (streaming + sync).
"""

import asyncio
import logging
import uuid
from collections.abc import AsyncGenerator

from fastapi import HTTPException, status

from core.config import get_settings
from api.chat.models import ChatResponse, ChatStreamEvent
from api.chat.mcp_server import create_mcp_server

logger = logging.getLogger(__name__)

# In-memory conversation history store: {conversation_id: [messages]}
# Each message is a dict with "role" and "content" keys.
# This is cleared on server restart.
_conversation_store: dict[str, list[dict]] = {}


def build_system_prompt() -> str:
    """Return the agent system prompt describing the NGS360 domain and behavior."""
    return """You are a helpful genomics data assistant for the NGS360 platform. \
You help users query and manage Next Generation Sequencing (NGS) data through \
natural language.

IMPORTANT: Do NOT include <thinking> tags or any internal reasoning in your \
responses. Respond directly to the user with clear, helpful answers.

## Domain Knowledge

NGS360 tracks the lifecycle of sequencing projects:

- **Projects** contain samples and are the top-level organizational unit.
- **Samples** are biological specimens registered within a project.
- **Sequencing Runs** represent a single run on a sequencing instrument, \
identified by a barcode.
- **QC Metrics** are quality-control records collected per pipeline execution. \
They can be workflow-level, single-sample, or paired-sample (e.g. tumor/normal).
- **Files** are tracked with a many-to-many association pattern — a file can \
belong to multiple projects, runs, samples, or QC records.
- **Workflows** define bioinformatics analysis steps (e.g. alignment, variant \
calling). Each workflow can have multiple execution runs.
- **Pipelines** are higher-level definitions that orchestrate one or more \
workflows.
- **Jobs** represent batch processing tasks submitted to AWS Batch.
- **Search** provides cross-entity full-text queries across all entity types.

## Behavior Guidelines

1. **Prefer reads before writes.** Always look up data before attempting to \
create or modify resources.
2. **Confirm before mutations.** Before submitting a demux workflow or pipeline \
job, summarize what you are about to do and ask the user to confirm.
3. **Chain tool calls** as needed to assemble a complete answer. For example, \
to find QC metrics for a project's samples, first list the project's samples, \
then search QC records.
4. **Be transparent about limitations.** If you cannot access certain data with \
the available tools, explain what is unavailable and suggest alternatives.
5. **Format responses with Markdown** for readability. Use tables for tabular \
data, code blocks for identifiers or paths, and lists for enumerations.
6. **Be concise but thorough.** Provide the information the user needs without \
unnecessary verbosity."""


def _create_mcp_tools(jwt_token: str) -> list:
    """
    Create MCP tools from the NGS360 MCP server for use with Strands Agent.

    Uses the MCPClient with streamable-http transport to connect to the
    in-process FastMCP server. Returns a list of tool objects the agent
    can use.
    """
    settings = get_settings()
    mcp_server = create_mcp_server(jwt_token, settings.CHAT_API_BASE_URL)

    # Extract tools directly from the FastMCP server's tool registry.
    # Each MCP tool wraps an NGS360 API call with the user's JWT.
    from strands import tool as strands_tool

    tools = []
    for name, mcp_tool in mcp_server._tool_manager._tools.items():
        fn = mcp_tool.fn
        # Wrap the MCP tool function as a Strands @tool
        wrapped = strands_tool(fn)
        tools.append(wrapped)

    return tools


def _create_session_manager(conversation_id: str | None, user_id: str):
    """
    Create an AgentCore Memory session manager for conversation persistence.

    Returns (session_manager, conversation_id) tuple. If AgentCore Memory
    is not configured (AGENTCORE_MEMORY_ID is None), returns (None, conv_id).
    """
    settings = get_settings()
    memory_id = settings.AGENTCORE_MEMORY_ID

    if not memory_id:
        # No memory configured — generate a conversation ID but skip memory
        conv_id = conversation_id or str(uuid.uuid4())
        return None, conv_id

    conv_id = conversation_id or str(uuid.uuid4())

    try:
        from bedrock_agentcore.memory.integrations.strands.config import (
            AgentCoreMemoryConfig,
        )
        from bedrock_agentcore.memory.integrations.strands.session_manager import (
            AgentCoreMemorySessionManager,
        )

        config = AgentCoreMemoryConfig(
            memory_id=memory_id,
            session_id=conv_id,
            actor_id=user_id,
        )
        session_manager = AgentCoreMemorySessionManager(
            agentcore_memory_config=config,
            region_name=settings.BEDROCK_REGION,
        )
        return session_manager, conv_id
    except Exception as e:
        logger.warning("Failed to initialize AgentCore Memory: %s", e)
        return None, conv_id


def create_agent(jwt_token: str, conversation_id: str | None, user_id: str):
    """
    Create a Strands Agent with MCP tools and optional conversation history.

    Args:
        jwt_token: The user's JWT for API authorization.
        conversation_id: Existing conversation ID, or None for new.
        user_id: The authenticated user's ID for memory scoping.

    Returns:
        (agent, conversation_id, memory_warning) tuple.
    """
    from strands import Agent
    from strands.models import BedrockModel
    import boto3

    settings = get_settings()

    # Create a fresh boto3 session per request to pick up current credentials
    session = boto3.Session(region_name=settings.BEDROCK_REGION)

    model = BedrockModel(
        model_id=settings.BEDROCK_MODEL_ID,
        boto_session=session,
    )

    tools = _create_mcp_tools(jwt_token)

    # Resolve conversation ID
    conv_id = conversation_id or str(uuid.uuid4())

    # Try AgentCore Memory first if configured
    session_manager = None
    memory_warning = None

    if settings.AGENTCORE_MEMORY_ID:
        session_manager, conv_id = _create_session_manager(
            conversation_id, user_id
        )
        if session_manager is None:
            memory_warning = (
                "Conversation history could not be loaded. "
                "Responding without prior context."
            )

    # Load in-memory conversation history
    messages = _conversation_store.get(conv_id, [])

    agent = Agent(
        model=model,
        tools=tools,
        system_prompt=build_system_prompt(),
        session_manager=session_manager,
        callback_handler=None,
        messages=messages if messages else None,
    )

    return agent, conv_id, memory_warning



async def process_message(
    user_jwt: str,
    user_id: str,
    message: str,
    conversation_id: str | None = None,
    stream: bool = True,
) -> AsyncGenerator[str, None] | ChatResponse:
    """
    Process a user message through the Strands Agent.

    Creates/loads conversation context from AgentCore Memory,
    initializes the agent with MCP tools, and returns the response.

    For stream=True, returns an AsyncGenerator yielding SSE-formatted strings.
    For stream=False, returns a ChatResponse with the full reply.

    Raises:
        HTTPException 503: Bedrock service unavailable
        HTTPException 504: Request timed out
        HTTPException 500: Unexpected agent error
    """
    settings = get_settings()

    try:
        agent, conv_id, memory_warning = create_agent(
            jwt_token=user_jwt,
            conversation_id=conversation_id,
            user_id=user_id,
        )
    except Exception as e:
        logger.error("Failed to create agent: %s", e)
        # Check if it's a Bedrock connectivity issue
        if _is_bedrock_error(e):
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="AI service is temporarily unavailable.",
            )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An error occurred while processing your message.",
        )

    if stream:
        return _stream_response(
            agent, message, conv_id, memory_warning, settings
        )
    else:
        return await _sync_response(
            agent, message, conv_id, memory_warning, settings
        )


def _is_bedrock_error(exc: Exception) -> bool:
    """Check if an exception is a Bedrock service error."""
    try:
        from botocore.exceptions import (
            ClientError,
            EndpointConnectionError,
            NoCredentialsError,
        )
        return isinstance(exc, (ClientError, EndpointConnectionError, NoCredentialsError))
    except ImportError:
        return False


def _is_bedrock_error_in_chain(exc: Exception) -> bool:
    """Check if a Bedrock error exists anywhere in the exception chain."""
    current = exc
    while current is not None:
        if _is_bedrock_error(current):
            return True
        current = current.__cause__ if current.__cause__ else current.__context__
        if current is exc:
            break  # avoid infinite loop
    return False


def _save_conversation(conversation_id: str, agent):
    """Save the agent's message history to the in-memory store."""
    try:
        _conversation_store[conversation_id] = list(agent.messages)
    except Exception as e:
        logger.warning("Failed to save conversation history: %s", e)


def _stream_response(
    agent,
    message: str,
    conversation_id: str,
    memory_warning: str | None,
    settings,
) -> AsyncGenerator[str, None]:
    """Stream agent response as SSE events."""

    async def event_generator() -> AsyncGenerator[str, None]:
        # Send memory warning as first event if applicable
        if memory_warning:
            evt = ChatStreamEvent(
                event="text",
                data=f"⚠️ {memory_warning}\n\n",
                conversation_id=conversation_id,
            )
            yield f"event: text\ndata: {evt.model_dump_json()}\n\n"

        try:
            # Use a deadline to enforce the timeout across the
            # entire streaming session rather than per-chunk.
            deadline = asyncio.get_event_loop().time() + settings.CHAT_TIMEOUT_SECONDS
            stream = agent.stream_async(message)

            async for event in stream:
                if asyncio.get_event_loop().time() > deadline:
                    raise asyncio.TimeoutError()

                if "data" in event:
                    text_chunk = event["data"]
                    if text_chunk:
                        evt = ChatStreamEvent(
                            event="text",
                            data=text_chunk,
                            conversation_id=conversation_id,
                        )
                        yield f"event: text\ndata: {evt.model_dump_json()}\n\n"

        except asyncio.TimeoutError:
            err = ChatStreamEvent(
                event="error",
                data="Request timed out.",
                conversation_id=conversation_id,
            )
            yield f"event: error\ndata: {err.model_dump_json()}\n\n"
            return

        except Exception as e:
            logger.error("Streaming error: %s", e)
            if _is_bedrock_error_in_chain(e):
                err_msg = "AI service is temporarily unavailable."
            else:
                err_msg = "An error occurred while processing your message."
            err = ChatStreamEvent(
                event="error",
                data=err_msg,
                conversation_id=conversation_id,
            )
            yield f"event: error\ndata: {err.model_dump_json()}\n\n"
            return

        # Send done event
        _save_conversation(conversation_id, agent)
        done = ChatStreamEvent(
            event="done",
            data="",
            conversation_id=conversation_id,
        )
        yield f"event: done\ndata: {done.model_dump_json()}\n\n"

    return event_generator()


async def _sync_response(
    agent,
    message: str,
    conversation_id: str,
    memory_warning: str | None,
    settings,
) -> ChatResponse:
    """Run agent synchronously and return a complete ChatResponse."""
    try:
        result = await asyncio.wait_for(
            agent.invoke_async(message),
            timeout=settings.CHAT_TIMEOUT_SECONDS,
        )
        response_text = str(result)

        _save_conversation(conversation_id, agent)

        if memory_warning:
            response_text = f"⚠️ {memory_warning}\n\n{response_text}"

        return ChatResponse(
            response=response_text,
            conversation_id=conversation_id,
        )

    except asyncio.TimeoutError:
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail="Request timed out.",
        )
    except Exception as e:
        logger.error("Agent error: %s", e)
        if _is_bedrock_error_in_chain(e):
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="AI service is temporarily unavailable.",
            )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An error occurred while processing your message.",
        )
