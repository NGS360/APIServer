# Option D Implementation Plan: Replace FileEntity with Typed Junction Tables

## Summary

Replace the polymorphic `fileentity` table with three dedicated, FK-backed junction tables — `fileproject`, `filerun`, `fileqcrecord` — matching the existing `filesample` pattern. This provides full referential integrity, cascade deletes, and type-safe ORM relationships for all file↔entity associations.

**Reference:** [filesample_vs_fileentity_sample.md](./filesample_vs_fileentity_sample.md) — Option D analysis

## Scope of Change

### Files Modified

| File | Summary |
|------|---------|
| `api/files/models.py` | Add 3 new SQLModel table classes; update `File` relationships; update request/response Pydantic models; remove `FileEntity`, `FileEntityType`, `EntityInput`, `EntityPublic` |
| `api/files/services.py` | Rewrite `create_file()`, `create_file_upload()`, `list_files_by_entity()`; remove `_validate_entity_exists()` |
| `api/files/routes.py` | Update `list_files` and `upload_file` route signatures and dispatch |
| `api/qcmetrics/services.py` | Update `_create_file_for_qcrecord()`, `delete_qcrecord()`, `_qcrecord_to_public()` |
| `alembic/env.py` | Update model imports |
| `alembic/versions/` | New migration script |
| `docs/FILE_MODEL.md` | Rewrite architecture section with new ERD |
| `tests/api/test_files_create.py` | Update `TestFileEntityType`, `TestFileCreateSchema` |
| `tests/api/test_files_routes.py` | Update upload tests — `entity_type`/`entity_id` form params change |
| `tests/api/test_qcmetrics.py` | Verify no breakage — mostly integration tests |

### Files Unchanged

- `api/samples/models.py` — `FileSample` and `Sample.file_samples` already correct
- `api/project/models.py` — may add optional `files` relationship later
- `api/runs/models.py` — may add optional `files` relationship later
- `api/qcmetrics/models.py` — no changes needed, only imports `FileCreate` and `FileSummary`

---

## Detailed Design

### 1. New Model Classes in `api/files/models.py`

#### FileProject

```python
class FileProject(SQLModel, table=True):
    __tablename__ = "fileproject"
    
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    file_id: uuid.UUID = Field(foreign_key="file.id", nullable=False)
    project_id: str = Field(foreign_key="project.project_id", max_length=50, nullable=False)
    role: str | None = Field(default=None, max_length=50)
    
    file: "File" = Relationship(back_populates="projects")
    
    __table_args__ = (
        UniqueConstraint("file_id", "project_id", name="uq_fileproject_file_project"),
    )
```

**FK target:** `project.project_id` — a `VARCHAR` column with a unique constraint, which is how callers identify projects today.

#### FileRun

```python
class FileRun(SQLModel, table=True):
    __tablename__ = "filerun"
    
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    file_id: uuid.UUID = Field(foreign_key="file.id", nullable=False)
    run_id: uuid.UUID = Field(foreign_key="sequencingrun.id", nullable=False)
    role: str | None = Field(default=None, max_length=50)
    
    file: "File" = Relationship(back_populates="runs")
    
    __table_args__ = (
        UniqueConstraint("file_id", "run_id", name="uq_filerun_file_run"),
    )
```

**FK target:** `sequencingrun.id` (UUID). Callers that reference runs by barcode must resolve barcode → UUID via `get_run()` first.

**Barcode resolution pattern:** Same as `resolve_or_create_sample()` — parse barcode, query `sequencingrun` table, return `id`. A new helper `resolve_run_by_barcode()` will be added to `api/runs/services.py`.

#### FileQCRecord

```python
class FileQCRecord(SQLModel, table=True):
    __tablename__ = "fileqcrecord"
    
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    file_id: uuid.UUID = Field(foreign_key="file.id", nullable=False)
    qcrecord_id: uuid.UUID = Field(foreign_key="qcrecord.id", nullable=False)
    role: str | None = Field(default=None, max_length=50)
    
    file: "File" = Relationship(back_populates="qcrecords")
    
    __table_args__ = (
        UniqueConstraint("file_id", "qcrecord_id", name="uq_fileqcrecord_file_qcrecord"),
    )
```

### 2. Updated File Model Relationships

Replace `File.entities` with three typed relationships:

```python
class File(SQLModel, table=True):
    # ... existing fields ...
    
    # Replace: entities: List["FileEntity"] = Relationship(...)
    projects: List["FileProject"] = Relationship(
        back_populates="file",
        sa_relationship_kwargs={"cascade": "all, delete-orphan"}
    )
    runs: List["FileRun"] = Relationship(
        back_populates="file",
        sa_relationship_kwargs={"cascade": "all, delete-orphan"}
    )
    qcrecords: List["FileQCRecord"] = Relationship(
        back_populates="file",
        sa_relationship_kwargs={"cascade": "all, delete-orphan"}
    )
    # Keep existing:
    hashes: List["FileHash"] = Relationship(...)
    tags: List["FileTag"] = Relationship(...)
    samples: List["FileSample"] = Relationship(...)
```

### 3. Updated Request Models

#### FileCreate — replace `entities` with typed association fields

```python
class FileCreate(SQLModel):
    uri: str
    original_filename: str | None = None
    size: int | None = None
    created_on: datetime | None = None
    source: str | None = None
    created_by: str | None = None
    storage_backend: str | None = None
    project_id: str | None = None  # Required when samples provided; also used for FileProject
    
    # REMOVED: entities: List[EntityInput] | None = None
    # NEW: typed association inputs
    run_ids: List[str] | None = None      # Barcode strings — resolved to UUID in service
    qcrecord_ids: List[str] | None = None  # UUID strings — for QCRECORD associations
    
    samples: List[SampleInput] | None = None
    hashes: dict[str, str] | None = None
    tags: dict[str, str] | None = None
```

**Key decision:** `project_id` already exists on `FileCreate` and is required when samples are provided. We reuse it for the `FileProject` association. If a `project_id` is supplied, a `FileProject` row is automatically created. This is simpler than a separate `project_ids` list since files are typically associated with exactly one project.

**`run_ids`:** Accepts barcode strings. The service layer resolves each to a `sequencingrun.id` UUID using `resolve_run_by_barcode()`. If a barcode cannot be resolved, a 404 is raised.

**`qcrecord_ids`:** Accepts UUID strings. The service layer creates `FileQCRecord` rows. This field is primarily used internally by QCMetrics — external callers rarely create file→qcrecord associations directly.

#### FileUploadCreate — replace entity_type/entity_id

Currently `FileUploadCreate` uses `entity_type: FileEntityType` and `entity_id: str`. This needs updating since there is no longer a polymorphic entity type.

**Option chosen:** Keep `entity_type` as a plain string and `entity_id` as a string, but remove the `FileEntityType` enum dependency. The service layer dispatches based on the string value:

```python
class FileUploadCreate(SQLModel):
    filename: str
    original_filename: str | None = None
    description: str | None = None
    entity_type: str  # "PROJECT" or "RUN" — plain string, no enum
    entity_id: str    # project_id string or run barcode string
    role: str | None = None
    is_public: bool = False
    created_by: str | None = None
    relative_path: str | None = None
    overwrite: bool = False
```

**Rationale:** The upload endpoint is used for PROJECT and RUN entity types only — it generates a URI path like `s3://bucket/{entity_type}/{entity_id}/filename`. We keep this interface simple. The service layer validates and resolves the entity, then creates the appropriate junction table row.

### 4. Updated Response Models

#### FilePublic — replace entities with typed associations

```python
class FileProjectPublic(SQLModel):
    project_id: str
    role: str | None

class FileRunPublic(SQLModel):
    run_id: str  # Return UUID as string for consistency
    role: str | None

class FileQCRecordPublic(SQLModel):
    qcrecord_id: str  # Return UUID as string
    role: str | None

class FilePublic(SQLModel):
    id: uuid.UUID
    uri: str
    filename: str
    original_filename: str | None
    size: int | None
    created_on: datetime
    created_by: str | None
    source: str | None
    storage_backend: str | None
    # REMOVED: entities: List[EntityPublic]
    # NEW:
    projects: List[FileProjectPublic]
    runs: List[FileRunPublic]
    qcrecords: List[FileQCRecordPublic]
    samples: List[FileSamplePublic]
    hashes: List[HashPublic]
    tags: List[TagPublic]
```

#### file_to_public() — updated serialization

```python
def file_to_public(file: File) -> FilePublic:
    return FilePublic(
        # ... existing fields ...
        projects=[
            FileProjectPublic(project_id=p.project_id, role=p.role)
            for p in file.projects
        ],
        runs=[
            FileRunPublic(run_id=str(r.run_id), role=r.role)
            for r in file.runs
        ],
        qcrecords=[
            FileQCRecordPublic(qcrecord_id=str(q.qcrecord_id), role=q.role)
            for q in file.qcrecords
        ],
        samples=[...],  # unchanged
        hashes=[...],    # unchanged
        tags=[...],      # unchanged
    )
```

### 5. Service Layer Changes

#### create_file() — api/files/services.py

Replace the `FileEntity` creation block with typed junction table creation:

```python
# Create project association
if file_create.project_id:
    project_assoc = FileProject(
        file_id=file_record.id,
        project_id=file_create.project_id,
    )
    session.add(project_assoc)

# Create run associations  
if file_create.run_ids:
    for run_barcode in file_create.run_ids:
        run = resolve_run_by_barcode(session, run_barcode)
        run_assoc = FileRun(
            file_id=file_record.id,
            run_id=run.id,
        )
        session.add(run_assoc)

# Create QCRecord associations
if file_create.qcrecord_ids:
    for qcrecord_id_str in file_create.qcrecord_ids:
        qcrecord_assoc = FileQCRecord(
            file_id=file_record.id,
            qcrecord_id=uuid.UUID(qcrecord_id_str),
        )
        session.add(qcrecord_assoc)
```

#### create_file_upload() — api/files/services.py

Replace `FileEntity` creation and `_validate_entity_exists()` call with typed dispatch:

```python
if file_upload.entity_type.upper() == "PROJECT":
    # Validate project exists via FK — attempt insert will fail if not
    project_assoc = FileProject(
        file_id=file_record.id,
        project_id=file_upload.entity_id,
        role=file_upload.role,
    )
    session.add(project_assoc)
elif file_upload.entity_type.upper() == "RUN":
    run = resolve_run_by_barcode(session, file_upload.entity_id)
    run_assoc = FileRun(
        file_id=file_record.id,
        run_id=run.id,
        role=file_upload.role,
    )
    session.add(run_assoc)
```

**Note:** `_validate_entity_exists()` is removed entirely. FK constraints handle existence validation at the DB level. For RUN, `resolve_run_by_barcode()` raises 404 if the barcode is not found. For PROJECT, an IntegrityError from the FK constraint is caught and converted to a 404.

#### New helper: resolve_run_by_barcode()

Added to `api/runs/services.py`:

```python
def resolve_run_by_barcode(session: Session, barcode: str) -> SequencingRun:
    """Resolve a run barcode to a SequencingRun record. Raises 404 if not found."""
    run_date, run_time, machine_id, run_number, flowcell_id = SequencingRun.parse_barcode(barcode)
    if run_date is None:
        raise HTTPException(status_code=404, detail=f"Invalid run barcode: {barcode}")
    run = session.exec(
        select(SequencingRun).where(
            SequencingRun.run_date == run_date,
            SequencingRun.machine_id == machine_id,
            SequencingRun.run_number == run_number,
            SequencingRun.flowcell_id == flowcell_id,
        )
    ).one_or_none()
    if not run:
        raise HTTPException(status_code=404, detail=f"Run not found: {barcode}")
    return run
```

#### Replace list_files_by_entity() with typed functions

```python
def list_files_by_project(session, project_id, include_archived=False, latest_only=True) -> List[File]:
    query = select(File).join(FileProject).where(FileProject.project_id == project_id)
    # ... archived filter + latest_only logic (same as current) ...

def list_files_by_run(session, run_id, include_archived=False, latest_only=True) -> List[File]:
    query = select(File).join(FileRun).where(FileRun.run_id == run_id)
    # ...

def list_files_by_qcrecord(session, qcrecord_id, include_archived=False, latest_only=True) -> List[File]:
    query = select(File).join(FileQCRecord).where(FileQCRecord.qcrecord_id == qcrecord_id)
    # ...
```

#### Route dispatch — api/files/routes.py

The `list_files` endpoint currently accepts `entity_type` and `entity_id` query params. Update to dispatch:

```python
if entity_type and entity_id:
    et = entity_type.upper()
    if et == "PROJECT":
        files = services.list_files_by_project(session, entity_id, ...)
    elif et == "RUN":
        run = resolve_run_by_barcode(session, entity_id)
        files = services.list_files_by_run(session, run.id, ...)
    elif et == "QCRECORD":
        files = services.list_files_by_qcrecord(session, uuid.UUID(entity_id), ...)
    else:
        raise HTTPException(400, f"Unknown entity_type: {entity_type}")
```

This preserves the same REST API query parameter interface — callers still pass `?entity_type=PROJECT&entity_id=P-123`.

### 6. QCMetrics Service Changes

#### _create_file_for_qcrecord() — api/qcmetrics/services.py:199

Replace `FileEntity` creation with `FileQCRecord`:

```python
# BEFORE:
entity_assoc = FileEntity(
    file_id=file_record.id,
    entity_type=entity_type,
    entity_id=str(entity_id),
)

# AFTER:
qcrecord_assoc = FileQCRecord(
    file_id=file_record.id,
    qcrecord_id=entity_id,  # Already a UUID
)
```

The function signature simplifies — no more `entity_type` parameter.

#### delete_qcrecord() — api/qcmetrics/services.py:399

Replace `FileEntity` lookup with `FileQCRecord`:

```python
# BEFORE:
file_entities = session.exec(
    select(FileEntity).where(
        FileEntity.entity_type == FileEntityType.QCRECORD,
        FileEntity.entity_id == str(record_uuid)
    )
).all()
for file_entity in file_entities:
    file_record = session.get(File, file_entity.file_id)
    if file_record:
        session.delete(file_record)

# AFTER:
file_qcrecords = session.exec(
    select(FileQCRecord).where(FileQCRecord.qcrecord_id == record_uuid)
).all()
for fqr in file_qcrecords:
    file_record = session.get(File, fqr.file_id)
    if file_record:
        session.delete(file_record)
```

#### _qcrecord_to_public() — api/qcmetrics/services.py:450

Replace `FileEntity` query with `FileQCRecord`:

```python
# BEFORE:
file_entities = session.exec(
    select(FileEntity).where(
        FileEntity.entity_type == FileEntityType.QCRECORD,
        FileEntity.entity_id == str(record.id)
    )
).all()
for file_entity in file_entities:
    file_record = session.get(File, file_entity.file_id)
    ...

# AFTER:
file_qcrecords = session.exec(
    select(FileQCRecord).where(FileQCRecord.qcrecord_id == record.id)
).all()
for fqr in file_qcrecords:
    file_record = session.get(File, fqr.file_id)
    ...
```

### 7. File.generate_uri() Update

Currently takes `entity_type: FileEntityType`. Change to accept a plain string:

```python
@staticmethod
def generate_uri(
    base_path: str,
    entity_type: str,  # Was: FileEntityType
    entity_id: str,
    filename: str,
    relative_path: str | None = None,
) -> str:
```

No functional change — it just calls `.lower()` on the string.

### 8. Alembic Migration

#### Migration steps

1. **Create** `fileproject` table with FK to `project.project_id`
2. **Create** `filerun` table with FK to `sequencingrun.id`
3. **Create** `fileqcrecord` table with FK to `qcrecord.id`
4. **Migrate data** from `fileentity`:
   - `entity_type=PROJECT` → `fileproject` rows, `entity_id` → `project_id`
   - `entity_type=RUN` → `filerun` rows, resolve barcode → `sequencingrun.id` UUID
   - `entity_type=QCRECORD` → `fileqcrecord` rows, cast `entity_id` to UUID → `qcrecord_id`
   - `entity_type=SAMPLE` → skip, no rows exist
5. **Drop** `fileentity` table

#### Downgrade

1. Recreate `fileentity` table
2. Reverse-migrate data from the three new tables back into `fileentity`
3. Drop the three new tables

### 9. Test Updates

#### tests/api/test_files_create.py

- **`TestFileEntityType`** — Remove entirely. No more `FileEntityType` enum.
- **`TestFileCreateSchema.test_full_file_create`** — Replace `entities=[EntityInput(...)]` with `run_ids=[...]` or just `project_id="P-123"`.
- Update imports: remove `FileEntityType`, `EntityInput`.

#### tests/api/test_files_routes.py

- `entity_type` and `entity_id` form params are still strings in the upload endpoint, so minimal change needed. The tests already pass `entity_type="project"` as strings.

#### tests/api/test_qcmetrics.py

- These are integration tests that go through the full HTTP API. They should pass without change since the internal `FileEntity` → `FileQCRecord` swap is transparent to the API consumer. The response format changes slightly — `output_files` in `QCRecordPublic` uses `FileSummary` which doesn't include entity associations.

### 10. Documentation Update

Update `docs/FILE_MODEL.md`:
- Replace `fileentity` table documentation with `fileproject`, `filerun`, `fileqcrecord`
- Update ERD to match the one in `filesample_vs_fileentity_sample.md` Section 5, Option D
- Update code reference section
- Remove `FileEntityType` references
- Update API endpoint documentation to reflect new request/response models

---

## Implementation Order

The implementation should proceed in this order to minimize broken intermediate states:

1. **Add new model classes** — `FileProject`, `FileRun`, `FileQCRecord` (additive, no breakage)
2. **Update `File` model relationships** — add `projects`, `runs`, `qcrecords` alongside `entities` temporarily
3. **Add `resolve_run_by_barcode()`** to runs services
4. **Update services** — `create_file()`, `create_file_upload()`, `list_files_by_*()`, qcmetrics services
5. **Update routes** — dispatch logic
6. **Update request/response models** — `FileCreate`, `FileUploadCreate`, `FilePublic`
7. **Remove old code** — `FileEntity`, `FileEntityType`, `EntityInput`, `EntityPublic`, `_validate_entity_exists()`, `File.entities` relationship
8. **Update alembic/env.py** imports
9. **Create migration**
10. **Update tests**
11. **Update docs**

## Risk Assessment

| Risk | Mitigation |
|------|------------|
| RUN barcode resolution fails for existing data | Migration uses same `parse_barcode()` logic; add error handling for unresolvable barcodes |
| Existing `fileentity` data has orphaned references | Migration logs warnings for rows that cannot be migrated — e.g., referencing deleted projects |
| API consumers depend on `entities` field in response | This is an internal API; update all callers. Response now has `projects`, `runs`, `qcrecords` |
| FK constraint violations during migration | Run migration in a transaction; validate data before insert |
