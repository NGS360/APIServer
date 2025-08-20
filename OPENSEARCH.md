## OpenSearch Implementation

### **Architecture Overview**

This application uses OpenSearch as a search engine to provide full-text search capabilities across genomics data entities (projects, samples, and sequencing runs).

### **Core Components**

#### **1. Configuration & Connection Management**
- **Location**: [`core/opensearch.py`](core/opensearch.py)
- **Connection**: Singleton pattern with global client instance
- **Configuration**: Environment-based settings from [`core/config.py`](core/config.py:54-57)
  - `OPENSEARCH_HOST`, `OPENSEARCH_PORT`
  - `OPENSEARCH_USER`, `OPENSEARCH_PASSWORD` (optional authentication)
- **Indexes**: Three predefined indexes: `["projects", "samples", "illumina_runs"]`

#### **2. Dependency Injection**
- **Location**: [`core/deps.py`](core/deps.py:17-24)
- **Pattern**: FastAPI dependency injection with type annotations
- **Usage**: `OpenSearchDep` provides OpenSearch client to route handlers
- **Error Handling**: Raises `RuntimeError` if client unavailable

#### **3. Application Lifecycle**
- **Location**: [`core/lifespan.py`](core/lifespan.py:37-39)
- **Initialization**: Automatically creates indexes on application startup
- **Logging**: Comprehensive configuration logging with sensitive data masking

### **Data Models**
#### **Search Models** ([`api/search/models.py`](api/search/models.py))
- `SearchAttribute`: Key-value pairs for metadata
- `SearchObject`: Core search entity (id, name, attributes)
- `SearchPublic`: Paginated search results container

### **Service Layer**
#### **Core Search Services** ([`api/search/services.py`](api/search/services.py))

**Indexing Function**: `add_object_to_index(client, object, index)`
- Transforms domain objects into search documents
- Document structure: `{id, name, attributes[]}`
- Includes index refresh for immediate availability

**Search Function**: `search(client, index, query, page, per_page)`
- Uses OpenSearch `query_string` for flexible search
- Searches across all fields (`fields: ['*']`)
- Implements pagination with `from/size` parameters

### **Integration Points**

#### **1. Projects** ([`api/project/services.py`](api/project/services.py:95-102))
- **Index**: `"projects"`
- **Indexed Fields**: Project ID, name, description
- **Trigger**: Automatic indexing on project creation

#### **2. Samples** ([`api/samples/services.py`](api/samples/services.py:77-84))
- **Index**: `"samples"`
- **Indexed Fields**: Sample ID, project association, metadata
- **Trigger**: Automatic indexing when samples added to projects

#### **3. Sequencing Runs** ([`api/runs/services.py`](api/runs/services.py:29-46))
- **Index**: `"sequencing_runs"` (note: different from predefined `"illumina_runs"`)
- **Indexed Fields**: Machine ID, flowcell ID, experiment name
- **Trigger**: Automatic indexing on run creation
- **Searchable Fields**: Defined by `__searchable__` attribute in model

### **API Endpoints**
#### **Search Endpoint** ([`api/search/routes.py`](api/search/routes.py))
```
GET /search?query=<term>&page=1&per_page=20
```
- **Current Limitation**: Hardcoded to search only `"projects"` index
- **Parameters**: Query string, pagination controls
- **Response**: Paginated search results

### **Architecture Patterns**

#### **1. Graceful Degradation**
- Application continues functioning if OpenSearch unavailable
- Comprehensive null-checking throughout the codebase
- Warning logs instead of failures when indexing fails

#### **2. Dual-Write Pattern**
- Data written to both primary database (SQLite/PostgreSQL) and OpenSearch
- OpenSearch acts as secondary index for search functionality
- No read-through caching implemented

#### **3. Document Structure**
```json
{
  "id": "unique_identifier",
  "name": "display_name", 
  "attributes": [
    {"key": "field_name", "value": "field_value"}
  ]
}
```

### **Current Limitations & Observations**

1. **Index Mismatch**: Runs service indexes to `"sequencing_runs"` but predefined indexes include `"illumina_runs"`
2. **Search Scope**: Search endpoint only queries projects index, not unified search
3. **No Bulk Operations**: Individual document indexing (could impact performance)
4. **No Index Mapping**: Uses default OpenSearch mappings
5. **Limited Query Features**: Basic query_string search without advanced features

### **Deployment Considerations**
- **Optional Dependency**: Application works without OpenSearch configured
- **Environment Variables**: All connection details configurable via environment
- **Security**: Supports authentication but SSL/TLS configuration commented out
- **Monitoring**: Comprehensive logging for troubleshooting

This implementation provides a solid foundation for search functionality while maintaining flexibility and fault tolerance in the genomics data management system.