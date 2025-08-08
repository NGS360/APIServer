"""
Define functions/aliases for dependency injection
"""
from collections.abc import Generator
from typing import Annotated, TypeAlias
from sqlmodel import Session
from fastapi import Depends
from opensearchpy import OpenSearch

from core.db import engine

# Define db dependency
def get_db() -> Generator[Session, None, None]:
  with Session(engine) as session:
    yield session

def get_opensearch_client() -> Generator[OpenSearch, None, None]:
  from core.opensearch import client  # Import the global client
  if client is None:
    raise RuntimeError("OpenSearch client is not available.")
  yield client

SessionDep: TypeAlias = Annotated[Session, Depends(get_db)]
OpenSearchDep: TypeAlias = Annotated[OpenSearch, Depends(get_opensearch_client)]
