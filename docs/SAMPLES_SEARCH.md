# Sample Search API

The Sample Search API provides two complementary search capabilities:

1. **Structured Search** (`/api/v1/samples/search`) - Filter samples by exact criteria (project, name, dates, attributes)
2. **Unified Free-Text Search** (`/api/v1/search`) - Search across projects, runs, and samples with a single query

---

## Structured Sample Search

Search samples using exact filters on project ID, sample name, creation date, and custom attributes.

### Endpoints

- `GET /api/v1/samples/search` - Search using query parameters
- `POST /api/v1/samples/search` - Search using JSON request body

Both endpoints return paginated results in the same format.

### Response Format

```json
{
  "data": [
    {
      "sample_id": "Sample_001",
      "project_id": "P-1234",
      "attributes": [
        {"key": "Tissue", "value": "Liver"},
        {"key": "USUBJID", "value": "CA123012-01-234"}
      ]
    }
  ],
  "data_cols": ["Tissue", "USUBJID"],
  "total_items": 42,
  "total_pages": 3,
  "current_page": 1,
  "per_page": 20,
  "has_next": true,
  "has_prev": false
}
```

**Response Fields:**
- `data` - Array of matching samples
- `data_cols` - List of all attribute keys found across matched samples (useful for building dynamic tables)
- Pagination metadata: `total_items`, `total_pages`, `current_page`, `per_page`, `has_next`, `has_prev`

---

## GET: Search with Query Parameters

Use query parameters for simple filtering.

### Examples

**Filter by project:**
```bash
GET /api/v1/samples/search?projectid=P-1234
```

**Filter by sample name:**
```bash
GET /api/v1/samples/search?samplename=Sample_001
```

**Filter by creation date:**
```bash
GET /api/v1/samples/search?created_on=2026-01-21
```

**Filter by custom attribute:**
```bash
GET /api/v1/samples/search?Tissue=Liver
```

**Multiple filters (AND logic):**
```bash
GET /api/v1/samples/search?projectid=P-1234&Tissue=Liver&created_on=2026-01-21
```

**With pagination:**
```bash
GET /api/v1/samples/search?projectid=P-1234&page=2&per_page=50
```

### Supported Query Parameters

| Parameter | Type | Description | Example |
|-----------|------|-------------|---------|
| `projectid` | string or list | Filter by project ID(s) | `projectid=P-1234` or `projectid=P-1234&projectid=P-5678` |
| `samplename` | string or list | Filter by sample name(s) | `samplename=Sample_001` |
| `created_on` | string | Filter by creation date (YYYY-MM-DD) | `created_on=2026-01-21` |
| `page` | integer | Page number (default: 1) | `page=2` |
| `per_page` | integer | Results per page (default: 20) | `per_page=50` |
| Any other key | string | Filter by custom attribute (case-insensitive key matching) | `Tissue=Liver` or `USUBJID=CA123012-01-234` |

**Notes:**
- Multiple values for the same parameter are OR'd together
- Different parameters are AND'd together
- Attribute key matching is case-insensitive (e.g., `tissue`, `Tissue`, `TISSUE` all match)
- Date filtering matches all samples created on that date

---

## POST: Search with JSON Body

Use POST for complex filtering, especially when working with tags or programmatic queries.

### Request Format

```json
{
  "filter_on": {
    "projectid": "P-1234",
    "samplename": "Sample_001",
    "created_on": "2026-01-21",
    "tags": {
      "USUBJID": "CA123012-01-234",
      "Tissue": "Liver"
    }
  },
  "page": 1,
  "per_page": 20
}
```

### Examples

**Basic filter:**
```bash
curl -X POST http://localhost:8000/api/v1/samples/search \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -d '{
    "filter_on": {
      "projectid": "P-1234"
    },
    "page": 1,
    "per_page": 20
  }'
```

**Filter by tags (custom attributes):**
```bash
curl -X POST http://localhost:8000/api/v1/samples/search \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -d '{
    "filter_on": {
      "tags": {
        "USUBJID": "CA123012-01-234",
        "Tissue": "Liver"
      }
    }
  }'
```

**Combined filters:**
```bash
curl -X POST http://localhost:8000/api/v1/samples/search \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -d '{
    "filter_on": {
      "projectid": "P-1234",
      "created_on": "2026-01-21",
      "tags": {
        "Tissue": "Liver"
      }
    },
    "page": 1,
    "per_page": 50
  }'
```

**List values (OR logic):**
```bash
curl -X POST http://localhost:8000/api/v1/samples/search \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -d '{
    "filter_on": {
      "projectid": ["P-1234", "P-5678"],
      "tags": {
        "Tissue": "Liver"
      }
    }
  }'
```

### Filter Behavior

| Filter Type | Behavior |
|-------------|----------|
| `projectid` | Exact match on project ID; list values are OR'd |
| `samplename` | Exact match on sample name; list values are OR'd |
| `created_on` | Date prefix match (YYYY-MM-DD format) |
| `tags` | Each key/value pair matched against sample attributes; keys are case-insensitive |
| Custom attributes | Any key not in the above list is treated as an attribute filter |
| Multiple filters | Combined with AND logic |

---

## Unified Free-Text Search

Search across projects, runs, and samples simultaneously using a single query string.

### Endpoint

```bash
GET /api/v1/search?query=MySample
```

### Response Format

```json
{
  "projects": {
    "data": [...],
    "total_items": 5,
    ...
  },
  "runs": {
    "data": [...],
    "total_items": 3,
    ...
  },
  "samples": {
    "data": [
      {
        "sample_id": "MySample_001",
        "project_id": "P-1234",
        "attributes": [...]
      }
    ],
    "total_items": 12,
    ...
  }
}
```

### Examples

**Search for a sample by name:**
```bash
GET /api/v1/search?query=MySample
```

**Search for samples in a project:**
```bash
GET /api/v1/search?query=P-1234
```

**Search with pagination:**
```bash
GET /api/v1/search?query=Sample&page=2&per_page=10
```

### Query Parameters

| Parameter | Type | Description | Default |
|-----------|------|-------------|---------|
| `query` | string | Free-text search query | Required |
| `page` | integer | Page number | 1 |
| `per_page` | integer | Results per page (applied to each entity type) | 5 |
| `sort_by` | string | Sort field | `sample_id` |
| `sort_order` | string | Sort order (`asc` or `desc`) | `asc` |

### Searchable Fields

For samples, the unified search matches on:
- `sample_id` - The sample name/identifier
- `project_id` - The project ID the sample belongs to

**Note:** Custom attributes are NOT searchable via unified search. Use structured search (`/api/v1/samples/search`) for attribute-level filtering.

---

## Authentication

All sample search endpoints require authentication. Include a valid JWT token in the Authorization header:

```bash
curl -X GET http://localhost:8000/api/v1/samples/search?projectid=P-1234 \
  -H "Authorization: Bearer YOUR_ACCESS_TOKEN"
```

---

## Use Cases

### Finding samples in a project

**GET:**
```bash
GET /api/v1/samples/search?projectid=P-1234
```

**POST:**
```json
POST /api/v1/samples/search
{
  "filter_on": {
    "projectid": "P-1234"
  }
}
```

### Finding samples with specific attributes

```json
POST /api/v1/samples/search
{
  "filter_on": {
    "projectid": "P-1234",
    "tags": {
      "Tissue": "Liver",
      "Disease": "Cancer"
    }
  }
}
```

### Finding samples created on a specific date

```bash
GET /api/v1/samples/search?created_on=2026-01-21&projectid=P-1234
```

### Finding samples across multiple projects

```json
POST /api/v1/samples/search
{
  "filter_on": {
    "projectid": ["P-1234", "P-5678", "P-9999"]
  }
}
```

### Quick search across all entity types

```bash
GET /api/v1/search?query=Sample_001
```

---

## Related Endpoints

- `POST /api/v1/samples/reindex` - Rebuild the OpenSearch index for samples (admin only)
- `GET /api/v1/projects/{project_id}/samples` - List all samples in a project
- `POST /api/v1/projects/{project_id}/samples` - Create a new sample

---

## Error Responses

**400 Bad Request** - Invalid query parameters or request body
```json
{
  "detail": "Invalid date format for created_on. Use YYYY-MM-DD."
}
```

**401 Unauthorized** - Missing or invalid authentication token
```json
{
  "detail": "Not authenticated"
}
```

**422 Unprocessable Entity** - Validation error
```json
{
  "detail": [
    {
      "loc": ["body", "page"],
      "msg": "ensure this value is greater than 0",
      "type": "value_error"
    }
  ]
}
```

---

## Best Practices

1. **Use POST for complex queries** - When filtering by multiple attributes or working programmatically, POST is cleaner than encoding everything in query params
2. **Use GET for simple queries** - For quick, human-readable filters (e.g., bookmarkable URLs)
3. **Leverage `data_cols`** - The response includes all attribute keys found in results, useful for building dynamic UI tables
4. **Page large result sets** - Use pagination to avoid loading too much data at once
5. **Use unified search for exploration** - When users are searching across entity types, `/api/v1/search` is faster than multiple calls
6. **Use structured search for precision** - When you need exact attribute matching or complex filters, use `/api/v1/samples/search`
