import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, create_engine, SQLModel
from sqlmodel.pool import StaticPool
from core.deps import get_db, get_opensearch_client
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
            return {
                "hits": {
                    "total": {"value": 0},
                    "hits": []
                }
            }
        
        # Extract search query
        query_info = body.get("query", {})
        search_term = ""
        
        if "query_string" in query_info:
            search_term = query_info["query_string"].get("query", "").lower()
        elif "match_all" in query_info:
            search_term = ""  # Match all documents
        
        # Filter documents based on search term
        hits = []
        for doc_id, doc_body in self.documents[index].items():
            should_include = False
            
            if not search_term:  # Empty search or match_all
                should_include = True
            else:
                # Search in name field
                if search_term in doc_body.get("name", "").lower():
                    should_include = True
                
                # Search in attributes
                for attr in doc_body.get("attributes", []):
                    if (search_term in attr.get("key", "").lower() or
                        search_term in attr.get("value", "").lower()):
                        should_include = True
                        break
            
            if should_include:
                hits.append({
                    "_id": doc_id,
                    "_source": doc_body,
                    "_score": 1.0
                })
        
        # Apply pagination
        from_param = body.get("from", 0)
        size_param = body.get("size", 10)
        paginated_hits = hits[from_param:from_param + size_param]
        
        return {
            "hits": {
                "total": {"value": len(hits)},
                "hits": paginated_hits
            }
        }
    
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


@pytest.fixture(name="client")
def client_fixture(session: Session, mock_opensearch_client: MockOpenSearchClient):
    def get_db_override():
        return session
    
    def get_opensearch_client_override():
        return mock_opensearch_client

    app.dependency_overrides[get_db] = get_db_override
    app.dependency_overrides[get_opensearch_client] = get_opensearch_client_override

    client = TestClient(app)
    yield client
    app.dependency_overrides.clear()


@pytest.fixture(name="opensearch_client")
def opensearch_client_fixture(mock_opensearch_client: MockOpenSearchClient):
    """Provide the mock OpenSearch client directly for tests that need it"""
    return mock_opensearch_client
