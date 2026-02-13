import os
import pytest

from fastapi.testclient import TestClient
from sqlmodel import Session, create_engine, SQLModel
from sqlmodel.pool import StaticPool

from core.config import get_settings
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
                # Search across ALL fields in the document (since they are already __searchable__)
                for field_name, field_value in doc_body.items():
                    if field_value and matches_query(str(field_value), search_term):
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
        paginated_hits = hits[from_param:from_param + size_param]

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

        # If delimiter is provided, return hierarchical listing (folders + files at this level)
        if self.delimiter:
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
        else:
            # No delimiter means recursive listing - return ALL files under prefix
            all_files = []
            for prefix_key, data in bucket_data.items():
                if prefix_key.startswith(self.prefix):
                    all_files.extend(data.get("files", []))

            # Build response page with all files
            page = {}
            if all_files:
                page["Contents"] = all_files

            yield page


class MockS3Client:
    """Mock S3 client for testing"""

    def __init__(self):
        self.buckets = (
            {}
        )  # Store bucket data: {bucket_name: {prefix: {"files": [], "folders": []}}}
        self.uploaded_files = {}  # Track uploaded files: {bucket: {key: body}}
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

                def paginate(self, Bucket: str, Prefix: str, Delimiter: str = None):
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

    def get_object(self, Bucket: str, Key: str, **kwargs):
        """Mock S3 get_object operation"""
        from botocore.exceptions import NoCredentialsError, ClientError

        # Check for simulated errors
        if self.error_mode == "NoCredentialsError":
            raise NoCredentialsError()
        elif self.error_mode == "NoSuchBucket":
            error_response = {
                "Error": {
                    "Code": "NoSuchBucket",
                    "Message": "The specified bucket does not exist",
                }
            }
            raise ClientError(error_response, "GetObject")
        elif self.error_mode == "AccessDenied":
            error_response = {
                "Error": {"Code": "AccessDenied", "Message": "Access Denied"}
            }
            raise ClientError(error_response, "GetObject")

        # Check if file exists in uploaded files
        if Bucket in self.uploaded_files and Key in self.uploaded_files[Bucket]:
            body = self.uploaded_files[Bucket][Key]

            # Create a mock response with Body attribute and read() method
            class MockBody:
                def __init__(self, content):
                    self.content = content

                def read(self):
                    return self.content

                def decode(self, encoding='utf-8'):
                    if isinstance(self.content, bytes):
                        return self.content.decode(encoding)
                    return self.content

            return {
                "Body": MockBody(body),
                "ContentType": "application/octet-stream",
                "ContentLength": len(body) if body else 0,
            }

        # File not found
        error_response = {
            "Error": {
                "Code": "NoSuchKey",
                "Message": "The specified key does not exist.",
            }
        }
        raise ClientError(error_response, "GetObject")

    def put_object(self, Bucket: str, Key: str, Body: bytes, **kwargs):
        """Mock S3 put_object operation"""
        from botocore.exceptions import NoCredentialsError, ClientError

        # Check for simulated errors
        if self.error_mode == "NoCredentialsError":
            raise NoCredentialsError()
        elif self.error_mode == "NoSuchBucket":
            error_response = {
                "Error": {
                    "Code": "NoSuchBucket",
                    "Message": "The specified bucket does not exist",
                }
            }
            raise ClientError(error_response, "PutObject")
        elif self.error_mode == "AccessDenied":
            error_response = {
                "Error": {"Code": "AccessDenied", "Message": "Access Denied"}
            }
            raise ClientError(error_response, "PutObject")

        # Store the uploaded file
        if Bucket not in self.uploaded_files:
            self.uploaded_files[Bucket] = {}
        self.uploaded_files[Bucket][Key] = Body

        return {"ETag": '"mock-etag"', "VersionId": "mock-version-id"}

    def head_object(self, Bucket: str, Key: str, **kwargs):
        """Mock S3 head_object operation - check if object exists"""
        from botocore.exceptions import NoCredentialsError, ClientError

        # Check for simulated errors
        if self.error_mode == "NoCredentialsError":
            raise NoCredentialsError()
        elif self.error_mode == "NoSuchBucket":
            error_response = {
                "Error": {
                    "Code": "NoSuchBucket",
                    "Message": "The specified bucket does not exist",
                }
            }
            raise ClientError(error_response, "HeadObject")
        elif self.error_mode == "AccessDenied":
            error_response = {
                "Error": {"Code": "AccessDenied", "Message": "Access Denied"}
            }
            raise ClientError(error_response, "HeadObject")

        # Check if file exists in uploaded files
        if Bucket in self.uploaded_files and Key in self.uploaded_files[Bucket]:
            body = self.uploaded_files[Bucket][Key]
            return {
                "ContentType": "application/octet-stream",
                "ContentLength": len(body) if body else 0,
                "ETag": '"mock-etag"',
            }

        # File not found - return 404
        error_response = {
            "Error": {
                "Code": "404",
                "Message": "Not Found",
            }
        }
        raise ClientError(error_response, "HeadObject")


class MockLambdaPayload:
    """Mock Lambda response payload"""

    def __init__(self, content: bytes):
        self.content = content

    def read(self) -> bytes:
        return self.content


class MockLambdaClient:
    """Mock Lambda client for testing"""

    def __init__(self):
        self.response_data = {}  # The response to return
        self.error_mode = None  # For simulating errors
        self.invocations = []  # Track invocations

    def set_response(self, response: dict):
        """Set the response that will be returned by invoke()"""
        self.response_data = response

    def simulate_error(self, error_type: str):
        """
        Configure client to raise specific errors

        Args:
            error_type: One of "ResourceNotFoundException", "AccessDeniedException",
                        "NoCredentialsError"
        """
        self.error_mode = error_type

    def invoke(self, FunctionName: str, InvocationType: str, Payload: str):
        """Mock Lambda invoke operation"""
        import json
        from botocore.exceptions import NoCredentialsError, ClientError

        # Track the invocation
        self.invocations.append({
            "FunctionName": FunctionName,
            "InvocationType": InvocationType,
            "Payload": json.loads(Payload)
        })

        # Check for simulated errors
        if self.error_mode == "NoCredentialsError":
            raise NoCredentialsError()
        elif self.error_mode == "ResourceNotFoundException":
            error_response = {
                "Error": {
                    "Code": "ResourceNotFoundException",
                    "Message": f"Function not found: {FunctionName}",
                }
            }
            raise ClientError(error_response, "Invoke")
        elif self.error_mode == "AccessDeniedException":
            error_response = {
                "Error": {
                    "Code": "AccessDeniedException",
                    "Message": "Access Denied"
                }
            }
            raise ClientError(error_response, "Invoke")

        # Return the configured response
        response_json = json.dumps(self.response_data).encode("utf-8")
        return {
            "StatusCode": 200,
            "Payload": MockLambdaPayload(response_json)
        }


@pytest.fixture(name="mock_lambda_client")
def mock_lambda_client_fixture():
    """Provide a mock Lambda client for testing"""
    return MockLambdaClient()


@pytest.fixture(name="test_project")
def test_project_fixture(session):
    """Provide a test project instance"""
    from api.project.models import Project

    project = Project(
        project_id="P-19900109-0001",
        name="Test Project"
    )
    session.add(project)
    session.commit()
    session.refresh(project)
    return project


@pytest.fixture(scope="session", autouse=True)
def isolate_test_environment():
    """Isolate tests from production environment variables"""
    # Clear the lru_cache for settings
    get_settings.cache_clear()

    # Store original env vars
    original_env = os.environ.copy()

    # Set test-specific environment variables
    os.environ["SQLALCHEMY_DATABASE_URI"] = "sqlite://"  # In-memory DB
    os.environ["OPENSEARCH_HOST"] = "localhost"
    os.environ["OPENSEARCH_PORT"] = "9200"
    os.environ["DATA_BUCKET_URI"] = "s3://test-data-bucket"
    os.environ["RESULTS_BUCKET_URI"] = "s3://test-results-bucket"
    os.environ["DEMUX_WORKFLOW_CONFIGS_BUCKET_URI"] = "s3://test-tool-configs-bucket"

    # Remove AWS credentials to prevent real AWS calls
    os.environ.pop("AWS_ACCESS_KEY_ID", None)
    os.environ.pop("AWS_SECRET_ACCESS_KEY", None)
    os.environ.pop("ENV_SECRETS", None)  # Prevent Secrets Manager lookup

    yield

    # Restore original environment
    os.environ.clear()
    os.environ.update(original_env)
    get_settings.cache_clear()


@pytest.fixture(autouse=True)
def reset_settings_cache():
    """Clear settings cache before each test"""
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture(name="session")
def session_fixture():
    """Provide a fresh database session for each test"""
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        pool_pre_ping=True
    )
    connection = engine.connect()
    SQLModel.metadata.create_all(bind=connection)

    session = Session(bind=connection, expire_on_commit=False)

    # Seed test settings
    from api.settings.models import Setting
    test_settings = [
        Setting(
            key="DATA_BUCKET_URI",
            value="s3://test-data-bucket",
            name="Data Bucket URI",
            description="Test data bucket"
        ),
        Setting(
            key="RESULTS_BUCKET_URI",
            value="s3://test-results-bucket",
            name="Results Bucket URI",
            description="Test results bucket"
        ),
        Setting(
            key="DEMUX_WORKFLOW_CONFIGS_BUCKET_URI",
            value="s3://test-tool-configs-bucket",
            name="Demux Workflow Configs Bucket URI",
            description="Test demux workflow configs bucket"
        ),
        Setting(
            key="MANIFEST_VALIDATION_LAMBDA",
            value="test-manifest-validation-lambda",
            name="Manifest Validation Lambda",
            description="Test Lambda function for manifest validation"
        ),
    ]
    for setting in test_settings:
        session.add(setting)
    session.commit()

    yield session

    # Cleanup: properly close session, connection, and dispose engine
    try:
        session.rollback()
    except Exception:
        pass
    finally:
        session.close()
        SQLModel.metadata.drop_all(bind=connection)
        connection.close()
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
    mock_lambda_client: MockLambdaClient,
    monkeypatch,
):
    """Provide a TestClient with dependencies overridden for testing"""
    import boto3
    from api.auth.models import User

    def get_db_override():
        return session

    def get_opensearch_client_override():
        return mock_opensearch_client

    def get_s3_client_override():
        return mock_s3_client

    def get_current_user_override():
        """Return a mock user for authentication"""
        return User(
            id="00000000-0000-0000-0000-000000000001",
            username="testuser",
            email="test@example.com",
            is_active=True,
            is_verified=True,
            is_superuser=False
        )

    # Patch boto3.client to return mock Lambda client for "lambda" service
    original_boto3_client = boto3.client

    def mock_boto3_client(service_name, **kwargs):
        if service_name == "lambda":
            return mock_lambda_client
        return original_boto3_client(service_name, **kwargs)

    monkeypatch.setattr(boto3, "client", mock_boto3_client)

    # Import auth dependencies
    from api.auth.deps import get_current_user

    app.dependency_overrides[get_db] = get_db_override
    app.dependency_overrides[get_opensearch_client] = get_opensearch_client_override
    app.dependency_overrides[get_s3_client] = get_s3_client_override
    app.dependency_overrides[get_current_user] = get_current_user_override

    client = TestClient(app)
    yield client
    app.dependency_overrides.clear()


@pytest.fixture(name="opensearch_client")
def opensearch_client_fixture(mock_opensearch_client: MockOpenSearchClient):
    """Provide the mock OpenSearch client directly for tests that need it"""
    return mock_opensearch_client
