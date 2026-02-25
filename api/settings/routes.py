"""
Routes/endpoints for the Settings API

HTTP   URI                          Action
----   ---                          ------
GET    /api/v1/settings             Get settings filtered by tag
GET    /api/v1/settings/[key]       Retrieve info about a specific setting
PUT    /api/v1/settings/[key]       Update info about a setting
"""

from fastapi import APIRouter, Query, status
from core.deps import SessionDep
from api.settings.models import Setting, SettingUpdate
from api.settings import services

router = APIRouter(prefix="/settings", tags=["Settings Endpoints"])


@router.get(
    "",
    response_model=list[Setting],
    status_code=status.HTTP_200_OK,
    tags=["Settings Endpoints"],
)
def get_settings_by_tag(
    session: SessionDep,
    tag_key: str = Query(..., description="Tag key to filter by"),
    tag_value: str = Query(..., description="Tag value to filter by"),
) -> list[Setting]:
    """
    Retrieve all settings that have a specific tag key-value pair.
    For example: tag_key="category" and tag_value="storage"
    """
    return services.get_settings_by_tag(
        session=session,
        tag_key=tag_key,
        tag_value=tag_value,
    )


@router.get(
    "/{key}",
    response_model=Setting,
    status_code=status.HTTP_200_OK,
    tags=["Settings Endpoints"],
)
def get_setting(session: SessionDep, key: str) -> Setting:
    """
    Retrieve a specific setting by key.
    """
    return services.get_setting_value(session=session, key=key)


@router.put(
    "/{key}",
    response_model=Setting,
    status_code=status.HTTP_200_OK,
    tags=["Settings Endpoints"],
)
def update_setting(
    session: SessionDep,
    key: str,
    setting_update: SettingUpdate,
) -> Setting:
    """
    Update a specific setting. Only the value, name, description, and tags can be updated.
    The key cannot be changed as it's the primary identifier.
    """
    return services.update_setting(
        session=session,
        key=key,
        update_request=setting_update,
    )
