"""
Routes/endpoints for the Users API
"""
from typing import Literal
from fastapi import APIRouter, Query, status
from core.deps import (
  SessionDep
)
from api.users.models import (
  User,
  UserCreate,
  UserPublic,
  UsersPublic
)
import api.users.services as services

router = APIRouter(prefix="/users", tags=["User Endpoints"])

@router.post(
  "",
  response_model=UserPublic,
  tags=["User Endpoints"],
  status_code=status.HTTP_201_CREATED
)
def create_user(session: SessionDep, user_in: UserCreate) -> User:
  """
  Create a new user with optional attributes.
  """
  return services.create_user(session=session, user_in=user_in)

@router.get(
  "",
  response_model=UsersPublic,
  tags=["User Endpoints"]
)
def get_users(
  session: SessionDep, 
  page: int = Query(1, description="Page number (1-indexed)"), 
  per_page: int = Query(20, description="Number of items per page"),
  sort_by: str = Query('user_id', description="Field to sort by"),
  sort_order: Literal['asc', 'desc'] = Query('asc', description="Sort order (asc or desc)")
) -> UsersPublic:
  """
  Returns a paginated list of users.
  """
  return services.get_users(
    session=session, 
    page=page,
    per_page=per_page,
    sort_by=sort_by,
    sort_order=sort_order
  )

@router.get(
  "/{user_id}",
  response_model=UserPublic,
  tags=["User Endpoints"]
)
def get_user_by_user_id(session: SessionDep, user_id: str) -> User:
  """
  Returns a single user by its user_id.
  Note: This is different from its internal "id".
  """
  return services.get_user_by_user_id(
    session=session,
    user_id=user_id
  )