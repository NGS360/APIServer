"""
Tools the AI Assistant chat agent can call.

Each tool is a plain function decorated with ``@tool``; LangChain generates the
schema from the signature and docstring, so keep the docstrings prescriptive
about *when* the model should call the tool.

The ``navigate`` tool is special: its side effect (redirecting the browser) is
performed by the frontend, which consumes a ``data-navigate`` SSE part emitted
by the streamer in ``services.py``. The string this tool returns is only what
the model sees as the tool result.
"""

from langchain_core.tools import tool

# Entity types the navigate tool can route to (must have detail pages in the app).
NAVIGABLE_TYPES = ("project", "run", "job")


@tool
def navigate(destination: str, id: str) -> str:
    """Take the user to an entity's detail page in NGS360.

    Call this when the user asks to open, go to, or view a specific project,
    run, or job.

    Args:
        destination: One of "project", "run", or "job".
        id: The entity id, e.g. "P-20260507-0008".
    """
    if destination not in NAVIGABLE_TYPES:
        return (
            f"Cannot navigate to '{destination}'. "
            f"Valid destinations are: {', '.join(NAVIGABLE_TYPES)}."
        )
    return f"Navigating to {destination} {id}."


@tool
def lookup_project(project_id: str) -> str:
    """Look up summary information about a project by its id.

    Call this when the user asks about a specific project's status, samples,
    or runs and you need real data to answer.

    Args:
        project_id: The project id, e.g. "P-20260507-0008".
    """
    # TODO: call the project service / DB here and return a concise summary.
    return f"Project {project_id}: <summary not yet wired up>."


TOOLS = [navigate, lookup_project]
