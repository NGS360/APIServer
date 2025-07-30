"""
Define functions/aliases for dependency injection
"""
from collections.abc import Generator
from typing import Annotated, TypeAlias
from sqlmodel import Session
from fastapi import Depends

from core.db import get_engine

# Define db dependency
def get_db() -> Generator[Session, None, None]:
  with Session(get_engine()) as session:
    yield session
  
SessionDep: TypeAlias = Annotated[Session, Depends(get_db)]