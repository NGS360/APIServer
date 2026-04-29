# Settings Create Endpoint (POST)

## Context

Currently, the Settings API only supports:
- **GET** `/api/v1/settings?tag_key=...&tag_value=...` — list settings by tag
- **GET** `/api/v1/settings/{key}` — read a single setting
- **PUT** `/api/v1/settings/{key}` — update an existing setting (404s if key doesn't exist)

There is **no POST endpoint** to create new settings. This means all settings must be pre-seeded via alembic data migrations. Any new setting (like `MANIFEST_VALIDATION_LAMBDA_QUALIFIER`) requires a code change and deployment to add, even though the value itself is purely configuration.

## Problem

Without a create endpoint, the workflow for adding a new runtime-configurable setting is:
1. Developer writes an alembic migration to seed the row
2. Code is reviewed, merged, deployed
3. Migration runs against the production database

This couples **configuration** to **deployment**, which is undesirable when:
- Ops teams need to add settings without developer involvement
- New Lambda qualifiers, bucket URIs, or feature flags need to be configured per-environment
- A frontend settings management UI wants to allow creating new keys

## Proposed Changes

### 1. Add `SettingCreate` model to `api/settings/models.py`

```python
class SettingCreate(SQLModel):
    """Data needed to create a new setting."""
    key: str = Field(max_length=255)
    value: str
    name: str = Field(max_length=255)
    description: str | None = None
    tags: list[dict[str, str]] | None = None
```

### 2. Add `create_setting()` to `api/settings/services.py`

```python
def create_setting(session: SessionDep, setting_create: SettingCreate) -> Setting:
    """Create a new setting. Raises 409 if key already exists."""
    existing = session.exec(
        select(Setting).where(Setting.key == setting_create.key)
    ).first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Setting with key '{setting_create.key}' already exists"
        )
    
    setting = Setting.model_validate(setting_create)
    session.add(setting)
    session.commit()
    session.refresh(setting)
    return setting
```

### 3. Add POST route to `api/settings/routes.py`

```python
@router.post(
    "",
    response_model=Setting,
    status_code=status.HTTP_201_CREATED,
    tags=["Settings Endpoints"],
)
def create_setting(
    session: SessionDep,
    setting_create: SettingCreate,
) -> Setting:
    """Create a new application setting."""
    return services.create_setting(session=session, setting_create=setting_create)
```

### 4. Tests in `tests/api/test_settings.py`

- **201** — Create a new setting with valid data
- **409** — Attempt to create a setting with a duplicate key
- **422** — Missing required fields (key, value, name)
- **GET after POST** — Verify the created setting is retrievable
- **PUT after POST** — Verify the created setting is updatable

## Discussion Points

1. **Authorization**: Should creating settings require superuser privileges? Currently PUT has no authorization check beyond authentication.
2. **Key validation**: Should we restrict allowed key formats (e.g., uppercase snake_case only)?
3. **Bulk create**: Should we support creating multiple settings in one request?
4. **DELETE endpoint**: If we add POST, should we also add DELETE? Currently there's no way to remove a setting either.
5. **Immutable keys**: Some settings (like bucket URIs) may be too dangerous to create ad-hoc. Should there be a whitelist/allowlist mechanism?

## Impact on This PR

For the current `MANIFEST_VALIDATION_LAMBDA_QUALIFIER` setting, we're using an alembic data migration to seed it. Once a POST endpoint exists, future settings could be created at runtime without requiring a migration + deployment cycle.
