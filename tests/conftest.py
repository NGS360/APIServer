import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, create_engine, SQLModel
from sqlmodel.pool import StaticPool
from core.deps import get_db, get_opensearch_client, get_s3_client
from main import app


class MockOpenSearchClient:
    """Mock OpenSearch client for testing"""

    def __init__(self):
        self.documents = {}  # Store documents by index
        self.indices_data = {}  # Store index metadata

    def index(self, index: str, id: str, body: dict):
        """Mock index operation"""
        if index not in self.documents:
            self.documents[index] = {}
        self.documents[index][id] = body
        return {"_id": id, "_index": index, "result": "created"}

    def search(self, index: str, body: dict):
        """Mock search operation"""
        if index not in self.documents:
            return {"hits": {"total": {"value": 0}, "hits": []}}

        # Extract search query
        query_info = body.get("query", {})
        search_term = ""

        if "query_string" in query_info:
            search_term = query_info["query_string"].get("query", "").lower()
        elif "match_all" in query_info:
            search_term = ""  # Match all documents

        # Parse wildcard queries like (*AI*)
        def parse_wildcard_query(query_term):
            """Convert OpenSearch wildcard query to simple substring search"""
            # Remove parentheses and convert (*term*) to just term
            if query_term.startswith("(*") and query_term.endswith("*)"):
                return query_term[2:-2]  # Remove (*..*)
            elif query_term.startswith("*") and query_term.endswith("*"):
                return query_term[1:-1]  # Remove *...*
            return query_term

        # Handle AND queries by splitting on " AND "
        def matches_query(text, query_term):
            """Check if text matches the query term (handling wildcards and AND)"""
            if " AND " in query_term:
                # Split on AND and check all terms match
                terms = [
                    parse_wildcard_query(term.strip())
                    for term in query_term.split(" AND ")
                ]
                return all(term in text.lower() for term in terms if term)
            else:
                # Single term
                parsed_term = parse_wildcard_query(query_term)
                return parsed_term in text.lower()

        # Filter documents based on search term
        hits = []
        for doc_id, doc_body in self.documents[index].items():
            should_include = False

            if not search_term:  # Empty search or match_all
                should_include = True
            else:
                # Search in name field
                if matches_query(doc_body.get("name", ""), search_term):
                    should_include = True

                # Search in attributes
                for attr in doc_body.get("attributes", []):
                    if matches_query(attr.get("key", ""), search_term) or matches_query(
                        attr.get("value", ""), search_term
                    ):
                        should_include = True
                        break

            if should_include:
                hits.append({"_id": doc_id, "_source": doc_body, "_score": 1.0})

        # Apply sorting if specified
        sort_config = body.get("sort", [])
        if sort_config:
            for sort_item in sort_config:
                if isinstance(sort_item, dict):
                    for field, sort_order in sort_item.items():
                        order = (
                            sort_order.get("order", "asc")
                            if isinstance(sort_order, dict)
                            else "asc"
                        )
                        reverse = order == "desc"

                        # Sort by the specified field
                        def get_sort_key(hit):
                            source = hit.get("_source", {})
                            # Remove .keyword suffix if present for compatibility with API
                            base_field = field.split(".")[0] if "." in field else field
                            value = source.get(base_field, "")
                            # Convert to string for consistent sorting
                            return str(value).lower() if value is not None else ""

                        hits.sort(key=get_sort_key, reverse=reverse)
                        break  # Only apply first sort for simplicity
                    break

        # Apply pagination
        from_param = body.get("from", 0)
        size_param = body.get("size", 10)
        paginated_hits = hits[from_param: from_param + size_param]

        return {"hits": {"total": {"value": len(hits)}, "hits": paginated_hits}}

    @property
    def indices(self):
        """Mock indices property"""
        return MockIndices(self)


class MockIndices:
    """Mock indices operations"""

    def __init__(self, client):
        self.client = client

    def exists(self, index: str):
        """Mock index exists check"""
        return index in self.client.indices_data

    def create(self, index: str, body=None):
        """Mock index creation"""
        self.client.indices_data[index] = body or {}
        if index not in self.client.documents:
            self.client.documents[index] = {}
        return {"acknowledged": True}

    def refresh(self, index: str):
        """Mock index refresh"""
        return {"_shards": {"total": 1, "successful": 1, "failed": 0}}


class MockS3Paginator:
    """Mock S3 paginator for list_objects_v2"""

    def __init__(self, client, bucket: str, prefix: str, delimiter: str):
        self.client = client
        self.bucket = bucket
        self.prefix = prefix
        self.delimiter = delimiter

    def paginate(self, **kwargs):
        """Return mock page iterator"""
        # Check if client is in error mode
        if self.client.error_mode:
            error_type = self.client.error_mode
            if error_type == "NoSuchBucket":
                from botocore.exceptions import ClientError

                error_response = {
                    "Error": {
                        "Code": "NoSuchBucket",
                        "Message": "The specified bucket does not exist",
                    }
                }
                raise ClientError(error_response, "ListObjectsV2")
            elif error_type == "AccessDenied":
                from botocore.exceptions import ClientError

                raise ClientError(
                    {"Error": {"Code": "AccessDenied", "Message": "Access Denied"}},
                    "ListObjectsV2",
                )
            elif error_type == "NoCredentialsError":
                from botocore.exceptions import NoCredentialsError

                raise NoCredentialsError()

        # Get bucket data
        bucket_data = self.client.buckets.get(self.bucket, {})
        prefix_data = bucket_data.get(self.prefix, {"files": [], "folders": []})

        # Build response page
        page = {}

        # Add CommonPrefixes (folders)
        if prefix_data["folders"]:
            page["CommonPrefixes"] = [
                {"Prefix": folder} for folder in prefix_data["folders"]
            ]

        # Add Contents (files)
        if prefix_data["files"]:
            page["Contents"] = prefix_data["files"]

        # Return single page (simplified for testing)
        yield page


class MockS3Client:
    """Mock S3 client for testing"""

    def __init__(self):
        self.buckets = (
            {}
        )  # Store bucket data: {bucket_name: {prefix: {"files": [], "folders": []}}}
        self.error_mode = None  # For simulating errors

    def setup_bucket(self, bucket: str, prefix: str, files: list, folders: list):
        """
        Setup mock data for a bucket/prefix

        Args:
            bucket: S3 bucket name
            prefix: S3 prefix/path
            files: List of file dicts with Keys, LastModified, Size
            folders: List of folder prefixes (strings ending with /)
        """
        if bucket not in self.buckets:
            self.buckets[bucket] = {}

        self.buckets[bucket][prefix] = {"files": files, "folders": folders}

    def get_paginator(self, operation: str):
        """Return a mock paginator"""
        if operation == "list_objects_v2":
            # Return a factory function that creates paginator with params
            def create_paginator(Bucket: str, Prefix: str, Delimiter: str):
                return MockS3Paginator(self, Bucket, Prefix, Delimiter)

            # Return object with paginate method
            class PaginatorFactory:
                def __init__(self, client):
                    self.client = client

                def paginate(self, Bucket: str, Prefix: str, Delimiter: str):
                    paginator = MockS3Paginator(self.client, Bucket, Prefix, Delimiter)
                    return paginator.paginate()

            return PaginatorFactory(self)

        raise NotImplementedError(f"Paginator for {operation} not implemented")

    def simulate_error(self, error_type: str):
        """
        Configure client to raise specific errors

        Args:
            error_type: One of "NoSuchBucket", "AccessDenied", "NoCredentialsError"
        """
        self.error_mode = error_type


@pytest.fixture(name="session")
def session_fixture():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    SQLModel.metadata.drop_all(engine)
    engine.dispose()


@pytest.fixture(name="mock_opensearch_client")
def mock_opensearch_client_fixture():
    """Provide a mock OpenSearch client for testing"""
    return MockOpenSearchClient()


@pytest.fixture(name="mock_s3_client")
def mock_s3_client_fixture():
    """Provide a mock S3 client for testing"""
    return MockS3Client()


@pytest.fixture(name="client")
def client_fixture(
    session: Session,
    mock_opensearch_client: MockOpenSearchClient,
    mock_s3_client: MockS3Client,
):
    def get_db_override():
        return session

    def get_opensearch_client_override():
        return mock_opensearch_client

    def get_s3_client_override():
        return mock_s3_client

    app.dependency_overrides[get_db] = get_db_override
    app.dependency_overrides[get_opensearch_client] = get_opensearch_client_override
    app.dependency_overrides[get_s3_client] = get_s3_client_override

    client = TestClient(app)
    yield client
    app.dependency_overrides.clear()


@pytest.fixture(name="opensearch_client")
def opensearch_client_fixture(mock_opensearch_client: MockOpenSearchClient):
    """Provide the mock OpenSearch client directly for tests that need it"""
    return mock_opensearch_client
