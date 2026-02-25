"""
Services for managing settings
"""
from fastapi import HTTPException, status
from sqlmodel import select
from core.deps import SessionDep
from api.settings.models import Setting, SettingUpdate


def update_setting(
    session: SessionDep,
    key: str,
    update_request: SettingUpdate
) -> Setting:
    """Update a specific setting"""
    setting = session.exec(
        select(Setting).where(Setting.key == key)
    ).first()
    if not setting:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Setting with key '{key}' not found"
        )

    # Update only the fields that are provided (not None)
    for field, value in update_request.model_dump(exclude_unset=True).items():
        setattr(setting, field, value)

    session.add(setting)
    session.commit()
    session.refresh(setting)

    return setting


def get_settings_by_tag(session: SessionDep, tag_key: str, tag_value: str) -> list[Setting]:
    """Get all settings that have a specific tag key-value pair"""
    # Get all settings
    all_settings = session.exec(select(Setting)).all()

    # Filter settings by tag in Python
    filtered_settings = []
    for setting in all_settings:
        if setting.tags:
            for tag in setting.tags:
                if tag.get('key') == tag_key and tag.get('value') == tag_value:
                    filtered_settings.append(setting)
                    break

    return filtered_settings


def get_setting_value(
    session: SessionDep,
    key: str
) -> str | None:
    """
    Get a setting value (string only) from the database.

    This is a convenience function for application code that needs config values
    without the full Setting object or exception handling.

    The database is the single source of truth for settings.

    Args:
        session: Database session
        key: Setting key to retrieve

    Returns:
        Setting value string or None if not found

    Example:
        >>> bucket_uri = get_setting_value(session, "DATA_BUCKET_URI")
    """
    try:
        # Get from database
        setting = session.exec(
            select(Setting).where(Setting.key == key)
        ).first()

        if setting and setting.value:
            return setting.value
    except Exception:
        # If DB query fails, return None
        pass

    return None
