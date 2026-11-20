from typing import Any

from jinja2.sandbox import SandboxedEnvironment

# OpenSearch utilities ----


def define_search_body(
    query: str, page: int, per_page: int, sort_by: str, sort_order: str
) -> dict:
    """
    Define the search body for OpenSearch queries.
    Includes sorting and pagination
    """
    # Handle wildcard query as a special case
    if query.strip() == "*":
        search_query = "*"
    else:
        search_list = query.split(" ")
        formatted_list = ["(*{}*)".format(token) for token in search_list]
        search_query = " AND ".join(formatted_list)

    search_body = {
        "query": {
            "query_string": {
                "query": search_query,
                "fields": ["*"],
            }
        },
        "from": (page - 1) * per_page,
        "size": per_page,
    }

    # Add sorting if sort_by is provided
    sort_field = f"{sort_by}.keyword"

    if sort_by and sort_order:
        search_body["sort"] = [{sort_field: {"order": sort_order}}]
    elif sort_by:
        # Default to ascending if only sort_by is provided
        search_body["sort"] = [{sort_field: {"order": "asc"}}]

    return search_body


# Template utilities ----


def interpolate(template: Any, context: dict) -> Any:
    """
    Interpolate a Jinja2 template with the provided context.
    Uses SandboxedEnvironment to prevent code execution vulnerabilities.

    A string is rendered. A dict or a list is interpolated value by value, to
    any depth, so a structure read from a configuration can be passed whole.
    Dict keys, and values that are neither strings, dicts nor lists, are
    returned as they are.

    Args:
        template: The template string to interpolate, or a structure holding
            template strings
        context: Dictionary of variables to pass to the template

    Returns:
        Interpolated string with variables substituted, or the structure with
        every string in it interpolated
    """
    if isinstance(template, str):
        return SandboxedEnvironment().from_string(template).render(context).strip()
    if isinstance(template, dict):
        return {key: interpolate(value, context) for key, value in template.items()}
    if isinstance(template, list):
        return [interpolate(item, context) for item in template]
    return template
