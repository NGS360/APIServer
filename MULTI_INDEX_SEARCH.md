# Multi-Index Search Implementation

## Overview

The search endpoint has been enhanced to support searching across multiple OpenSearch indexes simultaneously with individual pagination controls for each index. This provides powerful federated search capabilities while maintaining excellent performance through parallel execution.

## Key Features

✅ **Multi-Index Support**: Search across multiple indexes in a single request  
✅ **Parallel Execution**: All indexes are searched simultaneously for optimal performance  
✅ **Individual Pagination**: Each index maintains its own pagination state  
✅ **Error Resilience**: Partial failures don't break the entire response  
✅ **Rich Metadata**: Comprehensive response with success rates and summaries  
✅ **Backward Compatibility**: Single-index searches work seamlessly  

## API Endpoint

### `GET /search`

Search across multiple OpenSearch indexes with individual pagination per index.

#### Parameters

| Parameter | Type | Required | Description | Example |
|-----------|------|----------|-------------|---------|
| `indexes` | `List[str]` | ✅ | List of indexes to search | `["projects", "samples"]` |
| `query` | `str` | ✅ | Search query string | `"AI research"` |
| `page` | `int` | ❌ | Page number (1-indexed) | `1` |
| `per_page` | `int` | ❌ | Items per page (max 100) | `20` |
| `sort_by` | `str` | ❌ | Field to sort by | `"name"` |
| `sort_order` | `str` | ❌ | Sort order (`asc` or `desc`) | `"asc"` |

#### Available Indexes

- `projects` - Project data
- `samples` - Sample data  
- `illumina_runs` - Sequencing run data

## Usage Examples

### Single Index Search
```bash
GET /search?indexes=projects&query=AI&page=1&per_page=20
```

### Multi-Index Search
```bash
GET /search?indexes=projects&indexes=samples&query=test&page=1&per_page=10
```

### All Indexes with Sorting
```bash
GET /search?indexes=projects&indexes=samples&indexes=illumina_runs&query=data&sort_by=name&sort_order=desc
```

### Pagination Example
```bash
GET /search?indexes=projects&indexes=samples&query=research&page=3&per_page=5
```

## Response Structure

```json
{
  "results": {
    "projects": {
      "index_name": "projects",
      "items": [
        {
          "id": "proj_123",
          "name": "AI Research Project",
          "index_name": "projects",
          "attributes": [
            {"key": "status", "value": "active"}
          ]
        }
      ],
      "total": 150,
      "page": 1,
      "per_page": 20,
      "has_next": true,
      "has_prev": false,
      "success": true,
      "error": null,
      "total_pages": 8
    },
    "samples": {
      "index_name": "samples",
      "items": [
        {
          "id": "sample_456",
          "name": "DNA Sample Alpha",
          "index_name": "samples",
          "attributes": [
            {"key": "type", "value": "DNA"}
          ]
        }
      ],
      "total": 25,
      "page": 1,
      "per_page": 20,
      "has_next": false,
      "has_prev": false,
      "success": true,
      "error": null,
      "total_pages": 2
    }
  },
  "query": "AI",
  "page": 1,
  "per_page": 20,
  "total_across_indexes": 175,
  "indexes_searched": ["projects", "samples"],
  "partial_failure": false,
  "summary": {
    "projects": 150,
    "samples": 25
  },
  "success_rate": 100.0
}
```

## Response Fields

### Root Level
- `results`: Dictionary of index results (key = index name)
- `query`: The search query that was executed
- `page`: Page number applied to all indexes
- `per_page`: Items per page applied to all indexes
- `total_across_indexes`: Sum of totals from all successful indexes
- `indexes_searched`: List of indexes that were searched
- `partial_failure`: Boolean indicating if any index failed
- `summary`: Quick summary of total results per index
- `success_rate`: Percentage of successful index searches

### Per-Index Results
- `index_name`: Name of the index
- `items`: Array of search results for this index
- `total`: Total number of matching items in this index
- `page`: Current page number
- `per_page`: Items per page
- `has_next`: Whether there are more pages available
- `has_prev`: Whether there are previous pages
- `success`: Boolean indicating if this index search succeeded
- `error`: Error details if the search failed (null if successful)
- `total_pages`: Total number of pages for this index

### Search Items
- `id`: Unique identifier
- `name`: Display name
- `index_name`: Source index name
- `attributes`: Array of key-value attributes

## Pagination Behavior

### Synchronized Pagination
- All indexes use the same `page` and `per_page` parameters
- Each index maintains independent pagination state
- Different indexes may have different total counts

### Example Pagination Scenario
```
Request: page=2, per_page=20

Results:
- projects: Items 21-40 (total: 150, has_next: true)
- samples: Items 21-25 (total: 25, has_next: false)  
- illumina_runs: Items 21-40 (total: 75, has_next: true)
```

## Error Handling

### Graceful Degradation
The system continues to function even when some indexes fail, providing partial results rather than complete failure.

### Error Types
- `INDEX_NOT_FOUND`: Requested index doesn't exist
- `CONNECTION_ERROR`: Failed to connect to OpenSearch
- `TIMEOUT_ERROR`: Search operation timed out
- `QUERY_ERROR`: Invalid query syntax
- `PERMISSION_ERROR`: Access denied to index
- `UNKNOWN_ERROR`: Unexpected error occurred

### Partial Failure Example
```json
{
  "results": {
    "projects": {
      "success": true,
      "items": [...],
      "total": 25
    },
    "samples": {
      "success": false,
      "items": [],
      "total": 0,
      "error": {
        "index_name": "samples",
        "error_type": "timeout_error",
        "error_message": "Search timed out after 10 seconds",
        "timestamp": "2024-01-15T10:30:00Z"
      }
    }
  },
  "partial_failure": true,
  "success_rate": 50.0
}
```

## Performance Characteristics

### Parallel Execution
- All index searches execute simultaneously using `asyncio`
- Response time ≈ max(individual_search_times) instead of sum
- Configurable timeouts prevent hanging requests

### Optimization Features
- **Connection Pooling**: Efficient OpenSearch connection management
- **Request Deduplication**: Identical concurrent requests are merged
- **Result Size Limits**: Prevents excessive memory usage
- **Circuit Breaker**: Protects against cascading failures

### Performance Targets
- Multi-index search response time ≤ 2x single index time
- Memory usage increase <5% compared to single index
- 99.9% uptime with error resilience
- Cache hit rate >70% for repeated queries

## Implementation Details

### File Structure
```
api/search/
├── models.py          # Enhanced data models
├── services.py        # Multi-index search logic
├── routes.py          # Updated API endpoint
└── __init__.py

tests/api/
└── test_search.py     # Comprehensive test suite
```

### Key Components

#### Models (`api/search/models.py`)
- `SearchObject`: Enhanced with `index_name` field
- `IndexSearchResult`: Individual index result with error handling
- `MultiSearchPublic`: Complete multi-index response
- `SearchError`: Detailed error information

#### Services (`api/search/services.py`)
- `multi_search()`: Main multi-index search function
- `search_single_index_async()`: Async single index search
- `_create_error_result()`: Error result factory
- Comprehensive error handling and timeout management

#### Routes (`api/search/routes.py`)
- Updated endpoint with multi-index support
- Parameter validation and error responses
- Comprehensive API documentation

## Testing

### Test Coverage
- Single index search (backward compatibility)
- Multi-index search with various combinations
- Pagination edge cases and limits
- Error handling for each error type
- Performance with concurrent requests
- Computed fields and metadata

### Running Tests
```bash
python -m pytest tests/api/test_search.py -v
```

### Demo Script
```bash
python demo_multi_search.py
```

## Migration Notes

Since this is a new application without existing clients, no migration strategy is needed. The implementation provides a clean, modern API designed for multi-index search from the ground up.

### Breaking Changes from Original Design
- Parameter `index` (string) → `indexes` (array)
- Response structure changed from flat to nested by index
- New error handling with partial failure support

## Future Enhancements

### Potential Improvements
- **Cursor-based Pagination**: For very large result sets
- **Result Aggregation**: Merge results across indexes with unified sorting
- **Search Templates**: Pre-defined search configurations
- **Real-time Updates**: WebSocket support for live search results
- **Advanced Filtering**: Per-index filter parameters
- **Caching Layer**: Redis-based result caching

### Performance Optimizations
- **Streaming Results**: Return results as they become available
- **Adaptive Timeouts**: Dynamic timeout adjustment based on index performance
- **Load Balancing**: Distribute searches across multiple OpenSearch nodes
- **Query Optimization**: Automatic query rewriting for better performance

## Troubleshooting

### Common Issues

#### No Results Returned
- Verify index names are correct (check available indexes)
- Ensure OpenSearch is running and accessible
- Check query syntax and special characters

#### Partial Failures
- Check OpenSearch logs for specific error details
- Verify index permissions and access rights
- Monitor network connectivity and timeouts

#### Performance Issues
- Review query complexity and result set sizes
- Check OpenSearch cluster health and resources
- Consider adjusting timeout values and pagination limits

### Debug Information
- Enable detailed logging in `core/logger.py`
- Use `partial_failure` and `success_rate` fields to identify issues
- Check individual index `error` objects for specific failure details

## Support

For questions or issues with the multi-index search implementation:

1. Check the test suite for usage examples
2. Run the demo script to see expected behavior
3. Review OpenSearch logs for detailed error information
4. Consult the API documentation for parameter details

---

**Implementation Status**: ✅ Complete  
**Last Updated**: January 2024  
**Version**: 2.0.0