# OpenSearch utilities ----

def define_search_body(
    query: str, 
    page: int, 
    per_page: int, 
    sort_by: str, 
    sort_order: str
) -> dict:
  """
  Define the search body for OpenSearch queries.
  Includes sorting and pagination
  """
  search_list = query.split(" ")
  formatted_list = ["(*{}*)".format(token) for token in search_list]
  search_str = " AND ".join(formatted_list)

  search_body = {
    "query": {
        "query_string": {
              'query': search_str,
              "fields": ['*'],
        }
    },
    "from": (page - 1) * per_page,
    "size": per_page
  }

  # Add sorting if sort_by is provided
  sort_field = f"{sort_by}.keyword" # For API to work
  # sort_field = sort_by # For tests to work
  if sort_by and sort_order:
    search_body["sort"] = [
        {sort_field: {"order": sort_order}}
    ]
  elif sort_by:
    # Default to ascending if only sort_by is provided
    search_body["sort"] = [
        {sort_field: {"order": "asc"}}
    ]
  
  return search_body